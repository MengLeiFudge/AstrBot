# 云栖 AstrBot 部署

本仓库是基于 AstrBot v4.27.4 的云栖单账号部署分支。运行根、源码、脚本、本地插件和数据目录都在本仓库内，不依赖上级 `qqbot` 工作区的配置、插件或工具。

## 运行边界

- `ASTRBOT_ROOT` 固定为仓库根目录，真实运行数据位于 `data/`。
- 唯一 aiocqhttp 平台是云栖 `1443944862`，Reverse WebSocket 监听 `0.0.0.0:6200`。
- Dashboard 使用 `6185`；本地 artifact API 使用 `8080`。启动成功以三个端口都可连接为准。
- 夜凛、星遥和月澄不是本 AstrBot 的平台、persona 或 worker，只在云栖人格和插件防回环列表中作为静态姐妹关系。
- 启动不会自动更新源码或依赖版本。

## 启动

在 Windows PowerShell 中从仓库根目录执行：

```powershell
.\scripts\start.ps1
```

脚本使用本项目的 `uv` 环境运行 `main.py`。默认先执行 `uv sync`，再把 `deployment/extra-requirements.txt` 的固定插件依赖安装进本项目 `.venv`，并在 `6185`、`6200`、`8080` 就绪后返回。常用参数：

- `-ForceRestart`：终止命令行属于本项目的 AstrBot 进程后重新启动。
- `-SkipInstall`：已有 `.venv` 时跳过 `uv sync`。
- `-ReadyTimeoutSeconds 120`：设置端口就绪等待上限。

日志写入 `data/logs/astrbot.stdout.log` 和 `data/logs/astrbot.stderr.log`。脚本不会启动 NapCat。

## 更新

```powershell
.\scripts\update.ps1
```

更新脚本只处理本 AstrBot 仓库：通过 GitHub latest release API 获取 upstream 最新稳定 Release tag，显式 fetch 该 tag，合入本地 `deployment` 分支，再执行 `uv sync` 并刷新固定插件依赖。工作树必须干净；脚本不会 push，也不会在启动时自动运行。

配置示例见 `deployment/config-examples/`。示例不包含 provider key、平台 token、Dashboard secret 或其他运行凭据。漫画下载依赖与缓存边界见 `deployment/docs/adr/0001-isolate-comic-download-upstreams.md`。
