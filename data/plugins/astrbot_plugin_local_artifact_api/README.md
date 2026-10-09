# 本地产物发布接口

作者：MengLei

## 插件用途

本插件为云栖 AstrBot 提供本机 API，让本地构建流程通过 QQ 群文件发布 zip、dll 等构建产物。

它主要服务 `AfterBuildEvent.exe 1` 这类本机白名单构建流程，不是群聊指令插件，也不会响应普通聊天。

## 接口

- `POST /admin/api/artifacts/publish-local`
  - 固定监听 `127.0.0.1:8080`，只接受本机请求。
  - 校验请求时间、Git 上下文、文件路径和发布元数据。
  - `sha256` 校验 zip 文件本身。
  - `content_sha256` 只作为客户端声明的 zip 内容 hash；服务端会独立读取 zip 条目并计算内容 hash，不信任时间戳，也不只信任客户端传值。
  - 服务端内容 hash 与自身缓存一致时，直接跳过删除、上传和群消息。
  - 通过当前 AstrBot `aiocqhttp` OneBot 连接上传群文件。
  - 同一次请求向同一群上传多个变化文件时，先上传所有文件，最后只引用最后一个文件消息并发送一次发布说明。

## 部署地址

接口固定使用 `http://127.0.0.1:8080`，与项目启动脚本的就绪检查保持一致。
不提供 `host` / `port` 插件配置，也不再读取 `QQBOT_ASTRBOT_ARTIFACT_API_PORT` 环境变量。

## 运行边界

- 插件加载后监听本机接口，不依赖 profile 或 feature mode 环境变量。
- 使用项目 `scripts/start.ps1` 启动 AstrBot；该入口设置 `QQBOT_ASTRBOT_ACCOUNT=1443944862`，供发布接口识别云栖账号。
- 不读取 QQ 登录态、token、私聊记录或 AstrBot 运行日志。
- 发布状态来自 `data\plugin_data\qqbot_features_runtime`。

## 验证重点

- AstrBot 启动日志应出现本插件监听地址。
- 非 localhost 请求应返回 `403`。
- 构建产物发布失败时应返回明确 JSON 错误，不在群聊里泄露本机敏感路径以外的信息。
