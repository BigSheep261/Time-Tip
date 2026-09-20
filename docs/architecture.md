# TimeTip 架构说明

TimeTip 采用分层结构，依赖方向保持为“表现层 → 应用层 → 领域层”，基础设施层负责实现本地持久化和系统能力。入口只做对象组装，不放业务规则。

## 目录职责

- `app/domain`：日期、倒计时、工资、番剧等纯业务规则，不访问 Qt 窗口或文件系统。
- `app/application`：跨领域或跨存储实现的用例级规则，例如持久化番剧记录的统一规范化。
- `app/infrastructure`：SQLite、备份导入导出、更新、开机启动和单实例通信。
- `app/presentation`：Qt 页面、控件、对话框和用户交互。
- `app/bootstrap.py`：应用组合根，创建并连接 Store、窗口和单实例守卫。

持久化键统一定义在 `app/infrastructure/schema.py`。正式运行使用 SQLite；传入 INI 路径的 `Store` 仅用于隔离测试及旧格式兼容。两个后端必须复用应用层规范化函数，避免同一份数据因启动方式不同而产生不同结果。

## 数据与备份边界

用户结构化数据保存在 `timetip.sqlite3`，封面和表情图片保存在数据目录子文件夹。ZIP 备份中的路径必须是相对路径；导入只恢复 `data.json` 实际引用、且位于 `covers/` 或 `emojis/` 下的资源。数据库更新使用事务，单个资源文件使用临时文件原子替换。

备份格式版本由 `BACKUP_VERSION` 管理。新增设置或集合时，应同时更新 `schema.py`、兼容迁移和备份回归测试；不要在不同后端重复维护键名列表。

在线更新只接受 HTTP(S) 地址，先写入 `.part` 文件，完整下载后再原子替换；服务返回 SHA-256 时客户端必须校验通过。生产更新服务仍应优先部署 HTTPS，并在发布元数据中始终提供 SHA-256。

## 窗口职责与模块接入

本轮将日历提醒、追番页面、追番控件、设置以及窗口标题栏从主窗口分离：

- `presentation/calendar_page.py`：提醒增删、到期检查和日历标记。
- `presentation/anime_page.py`：追番列表、筛选、排序与编辑。
- `presentation/anime_widgets.py`：追番卡片、剧集列表和本地文件夹对话框。
- `presentation/settings_page.py`：设置、更新交互、数据恢复和模块开关。
- `presentation/chrome.py`：应用图标、Logo 和标题栏。

`presentation/module_runtime.py` 定义 `ModuleSpec`、`FeatureModule`、`ModuleContext` 和 `ModuleManager`。它负责 Qt 页面及资源生命周期，因此属于表现层。主窗口通过模块 ID 导航，并向已启用模块分派每秒计时；模块开关写入统一持久化模式。

新功能在 `app/features/__init__.py` 注册，由组合根传给主窗口，按需导入工厂。无须向主窗口添加继承、导航分支或定时任务。具体接口、示例、启停语义与打包要求见 [功能模块接入约定](feature-modules.md)。

旧页面通过 `builtin_modules.py` 兼容适配，仍保留 Mixin 和共享窗口状态。停用时保留控件树，停止对应调度与用户交互；新接口模块则释放页面和托管连接。概览与设置在当前阶段作为基础模块保持启用，旧页面编号仅作兼容用途。

后续逐个把内置适配器替换成持有自己数据与控件的独立 `FeatureModule`，再引入概览、日历和设置的贡献接口与模块数据模式注册。每次迁移一个边界，并验证启停、恢复、跨模块联动和资源清理；最终移除旧 Mixin 与数字索引接口。
