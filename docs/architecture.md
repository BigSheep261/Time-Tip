# TimeTip 开发架构

```text
timetip.py                    源码入口及旧 API 兼容
app/
  bootstrap.py                创建 Qt、单实例守卫、存储和主窗口
  domain/
    countdowns.py             周期、时段、显示状态和到期规则（无 Qt）
    anime.py                 放送日期、集数和分类规则（无 Qt）
    dates.py                 概览日期格式（无 Qt）
    salary.py                 工资与班次计算（无 Qt）
    layout.py                 组件网格排列（无 Qt）
  application/
    countdowns.py             保存校验、提醒状态推进（无 UI）
  infrastructure/
    store.py                  兼容旧设置与集合接口
    database.py               安装目录 SQLite、封面和导入导出
    single_instance.py        进程锁与本机 IPC
  presentation/
    window.py                 主窗口、概览、日历、番茄钟、备忘录及设置
    countdowns.py             倒计时表单和列表交互
    anime_dialog.py            番剧模态编辑对话框
    widgets.py                通用卡片、网格、缩放控件
    theme.py                  样式与颜色
tests/                        领域测试、Qt 回归与进程/安装集成检查
build_installer.ps1           测试、PyInstaller、C# 安装器、安装验证
build.bat                     双击构建入口
installer_stub.cs             校验、替换、恢复和启动安装结果
```

依赖方向：表现层调用应用层与领域层；应用层调用领域层；基础设施层提供存储和系统能力；`bootstrap.py` 组装依赖。领域层没有 Qt 依赖，时间以参数注入，便于模拟休眠、跨日和重启。

根目录中的 `timetip_core.py`、`timetip_widgets.py`、`timetip_single_instance.py` 保留为兼容导出；新代码直接从 `app` 对应层导入，业务实现不再放入根入口。现有其他页面仍由主窗口组织，可按功能继续拆分。

倒计时记录中的 `mode` 默认为 `standard`。循环记录使用 `cycle_start`、`cycle_end`、`frequency`、`cycle_weekdays` 描述规则，`notified_cycle` 是已提醒结束时间的最高记录；重复 tick、重启或系统时间回拨不会重复提醒。规则编辑后重建提醒基线，修改名称保留原状态。界面只在保存时提交表单。

默认数据迁移自旧注册表，之后使用安装目录下的 SQLite 数据库；升级无需更改数据位置。单实例锁串行化启动，锁持有者建立 IPC；第二次启动请求恢复窗口后退出。安装器先校验和解压，再请求已安装进程保存并退出，替换失败尝试回滚，只管理 `TimeTip.exe` 和 `_internal`。

`tests/verify_package.py` 用 `TIMETIP_TEST_PROFILE` 环境变量提供独立 INI 与测试通信名称，在 `build` 内运行真实 EXE 和安装逻辑；此变量仅供隔离测试，普通启动无需设置。验证不创建用户快捷方式，也不修改正式注册表配置。

番剧实体使用 `start_date`、`end_date`、`air_days`（单个星期）、`episode_count`、`progress`、`category` 和 `cover`。`episode_dates` 按首个不早于开始日期的目标星期逐周生成日期，并以结束日期和集数共同限制结果。`completed` 且进度达到总集数的记录不再出现在当天更新组件。

普通安装使用 SQLite 数据库，根目录由冻结程序所在目录的 `data` 子目录决定；源码调试可用 `TIMETIP_DATA_DIR` 指定。ZIP 导出包含 JSON 和数据库内封面文件，导入会校验结构并将封面放入新的 `data/covers`。
