# TimeTip 更新服务

该服务运行在 `47.116.193.23:8787`，与桌面端更新器的接口一致：

- `GET /api/update`：返回最新版本、下载地址和 SHA-256
- `GET /download/TimeTip-Setup-<版本>.exe`：下载安装包
- `POST /api/update/status`：客户端回报下载成功/失败、客户端 IP 和安装包来源
- `GET /admin`：浏览器管理界面，显示当前安装包、来源 IP 和更新结果
- `GET /health`：健康检查

服务启动时以及每次超过同步间隔访问 `/api/update` 时，会执行：

```text
git fetch origin release
git reset --hard origin/release
```

然后读取 `app/version.py` 的 `APP_VERSION`。服务数据目录默认是 `.timetip-updates`，自动拉取包保存为 `automatic/V<版本>/TimeTip-Setup-<版本>.exe`；Git 不可用时可人工放入同样结构的 `manual/V<版本>/` 目录。服务总是选择版本号最大的包。管理页面地址为 `http://47.116.193.23:8787/admin`。

`release/` 目录默认保存对应版本的安装包，推荐文件名为 `TimeTip-Setup-<版本>.exe`。发布分支需要提供以下任一种安装包来源：

1. 提交 `release/TimeTip-Setup.exe`（或带版本名的 `.exe`）；
2. 提交 `release/update.json`，内容至少包含 `url` 和 `sha256`，也可包含 `release_notes`。

当前仓库将 `.exe` 列入 `.gitignore`，发布分支已为 `release/` 目录保留例外。建议在 Windows 构建机生成安装包后，将对应版本的 `.exe` 放入 `release/` 目录并提交；如果安装包存放在外部 HTTPS 地址，也可以将 URL 和 SHA-256 写入 `release/update.json`。也可以通过 `TIMETIP_PACKAGE_PATH` 指向服务器上的本地安装包。

## 部署

在 Linux 服务器解压 `service_backend` 后可直接执行 `sudo bash install.sh`，脚本会安装 systemd 服务并设置开机启动；也可以按下面命令手动启动。

### Windows 服务器

项目目录（构建机上的 `service_backend`）如下：

```text
service_backend/
├─ server.py                       # 更新服务
├─ build_windows_installer.ps1    # 生成 Windows ZIP
├─ install_windows.ps1             # 注册 Windows 开机任务
├─ update.json.example             # 外部安装包地址示例
└─ README.md
```

运行安装脚本后，Windows 服务器上的目录为：

```text
C:\Program Files\TimeTipUpdateService\
└─ TimeTipUpdateService.exe

C:\ProgramData\TimeTipUpdateService\
├─ repo\                         # 服务自动 clone 的 release 分支
├─ automatic\                    # Git 自动拉取的安装包
│  └─ V1.4.1\TimeTip-Setup-1.4.1.exe
├─ manual\                       # Git 不可用时人工上传的安装包
│  └─ V1.4.1\TimeTip-Setup-1.4.1.exe
├─ metadata.json                 # 当前对外发布的包
└─ stats.jsonl                   # 客户端 IP、来源和下载结果
```

Git 发布分支应保持以下结构，版本号必须与 `app/version.py` 中的 `APP_VERSION` 一致：

```text
release/
├─ app/version.py                # APP_VERSION = "1.4.1"
└─ TimeTip-Setup-1.4.1.exe
```

首次部署时需要服务器安装 Git，并允许服务访问 GitHub；运行时不需要安装 Python，因为 ZIP 内含独立 EXE。Git 无法连接时，将安装包人工复制到 `C:\ProgramData\TimeTipUpdateService\manual\V版本\`，服务会自动扫描并回退到该目录。

在 Windows 构建机运行：

```powershell
.\build_windows_installer.ps1 -PythonExe C:\Path\To\python.exe
```

脚本会生成 `TimeTipUpdateService-Windows.zip`，解压后用管理员 PowerShell 运行 `install_windows.ps1`。它会把 `TimeTipUpdateService.exe` 注册为以 SYSTEM 身份开机启动、失败自动重启的 Windows 任务计划，数据目录默认为 `C:\ProgramData\TimeTipUpdateService`，并开放配置的 `8787` 端口。浏览器管理页面为 `http://47.116.193.23:8787/admin`。

可通过安装参数覆盖默认配置：

```powershell
.\install_windows.ps1 `
  -RepoUrl "https://github.com/BigSheep261/Time-Tip.git" `
  -PublicBaseUrl "http://47.116.193.23:8787" `
  -Port 8787 `
  -DataDir "D:\TimeTipUpdateService"
```

对应环境变量为 `TIMETIP_REPO_URL`、`TIMETIP_RELEASE_BRANCH`、`TIMETIP_UPDATE_ROOT`、`TIMETIP_PUBLIC_BASE_URL`、`TIMETIP_HOST` 和 `TIMETIP_PORT`。修改后运行 `Start-ScheduledTask -TaskName TimeTipUpdateService` 即可生效，可用 `Get-ScheduledTask -TaskName TimeTipUpdateService` 查看任务。

服务器安装 Git 和 Python 3.10+ 后：

```bash
git clone https://github.com/BigSheep261/Time-Tip.git /opt/timetip-update-service
cd /opt/timetip-update-service
export TIMETIP_UPDATE_ROOT=/var/lib/timetip-updates
export TIMETIP_PUBLIC_BASE_URL=http://47.116.193.23:8787
export TIMETIP_REPO_URL=https://github.com/BigSheep261/Time-Tip.git
export TIMETIP_RELEASE_BRANCH=release
python3 service_backend/server.py
```

生产环境建议使用 systemd，并在防火墙放行 TCP `8787`。如果前面配置了 Nginx，建议将公网接口改为 HTTPS，再把 `TIMETIP_PUBLIC_BASE_URL` 和桌面端的 `TIMETIP_UPDATE_URL` 都改成 HTTPS 地址。
