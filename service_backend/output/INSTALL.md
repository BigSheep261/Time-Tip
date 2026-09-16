# Time-Tip Service 安装说明

## 安装
将 Time-Tip-Service-Setup.exe 复制到目标 Windows x64 电脑，双击运行并允许管理员权限。
默认安装路径为 C:\Time-Tip-BackEnd。
安装包包含 Python 运行时、Flask Core、Vue 管理页面和 Windows 服务组件；目标机器不需要安装 Python 或 Node.js，安装过程不下载依赖。

## 登录
安装完成后打开 http://服务器IP:8788 。
首次登录的用户名和随机密码保存在：
C:\Time-Tip-BackEnd\ProgramData\config\initial-login.txt
登录配置文件为 backend_web\.env。
Core 地址和端口配置在 service_core\.env 中。默认 Core 为 8787，Web 为 8788。
修改配置后通过开始菜单 Restart Service 重启服务。

## 客户端安装包管理
管理员登录后手动上传 Windows x64 客户端 .exe 安装包，版本号格式为 VX.X.X，例如 V1.4.7。
保留安装包下载、删除、指定更新版本和下载记录功能。
已移除 GitHub 同步按钮、接口、启动及每日同步任务，新安装不生成 GitHub 配置。
原有 GitHub 安装包及下载记录继续保留，页面标记为“历史 GitHub”。
升级时保留原有 .env，里面残留的 GITHUB_* 和 PACKAGE_EXTENSIONS 配置不再读取。

## 运行与升级
服务名称：TimeTipService，启动类型：自动。
桌面快捷方式：Time-Tip Service。
开始菜单有 Start Service、Stop Service、Restart Service 和 Uninstall。
后端升级仍需手动运行新的安装包：先停止服务，再替换程序文件，然后启动服务。
已有的 .env、数据库和客户端安装包会保留。
卸载会停止并删除 Windows 服务，保留配置和 ProgramData 数据。

## 构建
使用 output/build_installer_release.ps1 构建。
可以通过 -PythonExe、-PackageManager 和 -NsisExe 指定 Python、pnpm/npm 及 NSIS 的路径。
-SkipDependencies 只跳过依赖安装，仍会检查后端运行依赖是否可导入。

## 验证范围
本次构建和运行验证结果见 test-results/smoke-report.json。
实际 Windows 服务注册、UAC 安装及卸载没有在本轮测试中执行。
