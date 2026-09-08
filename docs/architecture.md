# TimeTip 开发架构

```text
timetip.py                    源码入口及旧 API 兼容
app/
  bootstrap.py                创建 Qt、单实例守卫、存储和主窗口
  domain/
    countdowns.py             周期、时段、显示状态和到期规则（无 Qt）
    salary.py                 工资与班次计算（无 Qt）
    layout.py                 组件网格排列（无 Qt）
  application/
    countdowns.py             保存校验、提醒状态推进（无 UI）
  infrastructure/
    store.py                  QSettings、JSON 集合、旧数据迁移
    single_instance.py        进程锁与本机 IPC
  presentation/
    window.py                 主窗口、概览、日历、番茄钟、备忘录及设置
    countdowns.py             倒计时表单和列表交互
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

默认数据仍使用原注册表路径，升级无需更改数据位置。单实例锁串行化启动，锁持有者建立 IPC；第二次启动请求恢复窗口后退出。安装器先校验和解压，再请求已安装进程保存并退出，替换失败尝试回滚，只管理 `TimeTip.exe` 和 `_internal`。

`tests/verify_package.py` 用 `TIMETIP_TEST_PROFILE` 环境变量提供独立 INI 与测试通信名称，在 `build` 内运行真实 EXE 和安装逻辑；此变量仅供隔离测试，普通启动无需设置。验证不创建用户快捷方式，也不修改正式注册表配置。
