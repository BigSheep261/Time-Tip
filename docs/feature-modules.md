# 功能模块接入约定（API v1）

目标是让主窗口成为应用外壳，新增功能通过注册接入，模块的页面、定时任务和订阅由自己的生命周期管理。

## 本轮已经支持的能力

- `ModuleSpec` 描述唯一 ID、名称、工厂、接口版本、依赖、默认启用状态和导航可见性。
- `FeatureModule` 提供页面工厂以及启动、停用、计时、显示和隐藏钩子。
- `ModuleManager` 负责注册、按需导入、启停、依赖检查、导航及移除注册。
- 设置中的“功能模块”可以启停普通内置功能，状态保存在 `module_states`，随 JSON / ZIP 数据备份保存。
- 新接口模块停用时销毁页面、释放管理的信号连接与定时器；再次启用时重新实例化。
- 停用不会删除模块的用户数据。正在使用的页面停用后回到概览。
- 接口版本不兼容、ID 重复、依赖缺失或循环会报错。加载失败会回退本次新启用的依赖，不影响原先已启用的模块。

## 新增模块

在 `TimeTip-Application/app/features/` 中添加模块文件。例如 `example.py`：

```python
from PyQt6.QtWidgets import QLabel
from app.presentation.module_runtime import FeatureModule


class ExampleModule(FeatureModule):
    def create_page(self):
        self.label = QLabel("模块已加载")
        return self.label

    def start(self):
        self.context.subscribe("theme.changed", self.on_theme_changed)

    def tick(self, now):
        self.label.setText(now.strftime("%H:%M:%S"))

    def on_theme_changed(self, theme_id):
        self.label.setToolTip("当前主题：" + theme_id)
```

在 `app/features/__init__.py` 的注册表加入描述：

```python
from app.presentation.module_runtime import ModuleSpec

FEATURE_MODULES = (
    ModuleSpec(
        id="example",
        title="示例功能",
        factory="app.features.example:ExampleModule",
        api_version=1,
        default_enabled=False,
    ),
)
```

组合根会传入注册表，无须修改 `TimeTipWindow` 的继承列表、页面构建、导航编号或每秒计时逻辑。工厂字符串在启用时才通过 Python 导入，未启用的新接口模块不会实例化。

模块注册来自受信任的应用代码，备份中的模块状态只包含 ID 和布尔值，不用于导入代码。当前没有插件商店、任意 ZIP 安装器或目录自动扫描。

程序运行期间，也可以在 Qt 主线程中操作：

```python
window.modules.register(spec)
window.modules.enable(spec.id)
window.modules.navigate(spec.id)
window.modules.disable(spec.id)
window.modules.unregister(spec.id)
```

`enable` / `disable` / `unregister` 返回是否成功；失败原因在 `last_error`。`register` 对无效描述抛出 `ValueError`。移除注册只移除应用中的实例和入口，不删除 Python 文件，也不从 `sys.modules` 卸载代码；修改模块实现后仍应重启应用。

## 生命周期和资源责任

| 接口 | 约定 |
| --- | --- |
| `create_page()` | 返回 `QWidget`，仅构建界面，不启动后台任务。子控件归属返回的页面。 |
| `start()` | 加载状态，注册跨模块订阅及外部信号，启动任务。每次启用都会调用。 |
| `tick(now)` | 已启用时每秒调用，Qt 主线程执行，不能做网络请求或阻塞工作。 |
| `shown()` / `hidden()` | 页面切换时使用，适合暂停仅与可见界面有关的动画。 |
| `can_stop()` | 只读检查；工作无法安全停止时返回 `False`，不改变状态。 |
| `stop()` | 保存数据并停止、等待后台任务结束。失败应抛出异常，正常停用会保留仍未保存成功的页面。必须支持启动失败后的清理。 |

使用 `context.connect(signal, callback)` 连接外部信号，使用 `context.timer(milliseconds, callback)` 创建托管定时器。使用 `context.subscribe(event, callback)` 接收事件，`context.publish(event, payload)` 发布事件。启停周期结束时，托管连接、计时器、订阅自动释放；上一周期已排队的信号也会被忽略。

页面内部、生命周期与页面完全一致的控件信号可直接连接。窗口、全局服务等外部信号必须通过上下文连接，避免销毁页面后继续调用它。线程、文件句柄、非 Qt 异步任务仍由模块在 `stop()` 中结束；不能指望移除导航按钮代替结束任务。

其他服务：

- `context.navigate("模块ID")`：导航；目标未启用或不可见时返回 `False`，不会偷偷启用它。
- `context.notify(text)`：已启用模块发送通知。
- `context.store`：持久化入口。键使用自己的模块前缀，禁止覆盖其他模块的数据。新增需要全量备份的数据键或集合，仍须在 `infrastructure/schema.py` 注册并补备份测试；目前没有动态数据模式注册。
- `context.parent`：Qt 对话框的父窗口。新模块不应把它作为读取其他模块私有控件或业务状态的捷径。

当前公共事件有 `theme.changed`（主题 ID）、`data.reloaded`（恢复数据完成）、`modules.changed`（注册或启停变化）。事件接收方应重新读取所需数据，不保留其他模块的控件引用。

## 依赖与失败处理

`dependencies=("another_module",)` 表示硬依赖，启用时按顺序自动启用依赖；依赖存在已启用的使用者时不能直接停用。退出按依赖的反向顺序停止模块。可选联动使用事件和持久化数据，不声明不必要的硬依赖。

注册和生命周期操作在 Qt 主线程执行。`start()` / `stop()` 不应重入模块启停操作。启动失败必须能清理部分初始化资源；运行中无法停止的工作通过 `can_stop()` 明确拒绝停用。失败原因应显示给用户，不能只隐藏按钮。

## 当前迁移边界

本轮抽离了日历提醒、追番页面、追番专用控件、设置页面和窗口标题栏。旧页面通过 `builtin_modules.py` 的兼容适配器接入注册系统，仍使用原有 Mixin 和部分共享窗口状态。

兼容适配器使用 `retain_page=True`：启动时预建旧页面，停用后停止对应的调度和交互、保留页面对象，重新启用可保留编辑状态。它们目前支持启停，不支持移除注册。不能把这一阶段理解为所有历史功能已完全消除耦合。

| 内置功能 | 停用行为 |
| --- | --- |
| 日历提醒 | 停止到期检查并隐藏概览入口；重新启用后，延续原规则补发未通知的到期事项。 |
| 倒计时 | 停止通知调度并隐藏概览组件；重新启用后沿用原有补发和去重规则。 |
| 番茄钟 | 暂停并保留本次运行中的剩余时间，重新启用后等待手动继续。 |
| 备忘录 | 先保存编辑内容；保存失败拒绝停用。 |
| 追番 | 隐藏入口、概览更新与日历番剧标记，保留全部记录。编辑窗口打开时拒绝停用。 |
| 表情包 | 隐藏页面，利用现有隐藏事件暂停动图。 |
| 塔罗 | 隐藏页面并停止滚动计时器，保留本次会话抽牌。 |
| JM | 运行任务存在时拒绝停用；原隐藏入口规则保留，不列入普通模块开关。 |
| 概览、设置 | 作为本阶段的基础外壳保持启用，确保始终有返回入口和模块管理入口。 |

后续应逐个把旧适配器替换为真正的 `FeatureModule`，让数据状态、页面控件和资源都归模块持有；随后把概览贡献、日历贡献、模块设置和数据模式做成注册接口。先迁移独立模块，再解除设置与概览的共享控件依赖，最终移除对应 Mixin 与固定索引兼容。

## 打包与验证

PyInstaller 配置收集 `app.features` 的子模块，保证字符串工厂在安装版中可导入。放在其他 Python 包的扩展及非代码资源，需要在打包配置中明确包含；添加新模块后须重新构建安装包。

运行 `python -m unittest discover -s tests -v`。新增模块至少验证启用、停用、再次启用、活动页面卸载、未保存内容、后台资源清理及必需依赖。业务数据需要备份时，还要验证 JSON / ZIP 往返恢复。
