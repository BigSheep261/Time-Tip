# Time-Tip Service 安装说明

## 安装
将 Time-Tip-Service-Setup.exe 复制到目标 Windows x64 电脑，双击运行并允许一次管理员权限。
默认安装路径为 C:\Time-Tip-BackEnd。
安装包包含 Python 运行时、Flask Core、Vue 3 构建文件和 Windows 服务包装程序；目标机器不需要 Python 或 Node.js，安装过程不下载依赖。

## 登录
安装完成后打开 http://服务器IP:8788 。
首次登录的用户名和随机密码保存在：
C:\Time-Tip-BackEnd\ProgramData\config\initial-login.txt
登录配置文件为 backend_web\.env。
Core 地址、端口及 GitHub 配置在 service_core\.env 中。默认 Core 为 8787，Web 为 8788。
修改配置后通过开始菜单 Restart Service 重启服务。

## 运行与升级
服务名称：TimeTipService，启动类型：自动。
桌面快捷方式：Time-Tip Service。
开始菜单有 Start Service、Stop Service、Restart Service 和 Uninstall。
再次运行安装包会先停止服务，再替换程序文件，然后启动服务。
已有的 .env、数据库和更新安装包会保留。
卸载会停止并删除 Windows 服务，保留配置和 ProgramData 数据。

## 验证记录
本机已通过：Vue 构建、Python 编译、打包程序启动、双 HTTP 端口、Edge 浏览器登录、配置生成和保留、上传/检查/下载、版本与来源统计、服务包装程序启动/停止。
测试进程 PATH 不包含 Python 或 Node.js。
当前测试进程无 Windows 管理员令牌，因此未实际安装系统服务或执行 UAC 安装/卸载测试；服务注册将在目标机器安装时执行。
详见 test-results/smoke-report.json。
