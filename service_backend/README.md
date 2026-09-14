# TimeTip 更新服务

该服务运行在 `47.116.193.23:8787`，与桌面端更新器的接口一致：

- `GET /api/update`：返回最新版本、下载地址和 SHA-256
- `GET /download/TimeTip-Setup-<版本>.exe`：下载安装包
- `GET /health`：健康检查

服务启动时以及每次超过同步间隔访问 `/api/update` 时，会执行：

```text
git fetch origin release
git reset --hard origin/release
```

然后读取 `app/version.py` 的 `APP_VERSION`。`release/` 目录默认保存对应版本的安装包，推荐文件名为 `TimeTip-Setup-<版本>.exe`。发布分支需要提供以下任一种安装包来源：

1. 提交 `release/TimeTip-Setup.exe`（或带版本名的 `.exe`）；
2. 提交 `release/update.json`，内容至少包含 `url` 和 `sha256`，也可包含 `release_notes`。

当前仓库将 `.exe` 列入 `.gitignore`，发布分支已为 `release/` 目录保留例外。建议在 Windows 构建机生成安装包后，将对应版本的 `.exe` 放入 `release/` 目录并提交；如果安装包存放在外部 HTTPS 地址，也可以将 URL 和 SHA-256 写入 `release/update.json`。也可以通过 `TIMETIP_PACKAGE_PATH` 指向服务器上的本地安装包。

## 部署

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
