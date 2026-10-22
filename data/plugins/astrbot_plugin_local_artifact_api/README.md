# 本地产物发布接口

作者：MengLei

## 插件用途

本插件为云栖 AstrBot 提供本机 API，让本地构建流程通过 QQ 群文件发布 zip、dll 等构建产物。

它主要服务 `AfterBuildEvent.exe 1` 这类本机白名单构建流程，不是群聊指令插件，也不会响应普通聊天。

## 接口

- `GET /admin/api/artifacts/group-files?group_id=<群号>&folder_id=<文件夹ID>`：仅供本机核对目标目录的文件 ID、名称及大小，查询上限 30 秒；用于上传超时后核对实际状态，不能把名称/大小相同视为内容哈希确认。

- `POST /admin/api/artifacts/group-folders`
  - 仅接受本机 JSON 请求 `{"group_id": 319567534, "folder_name": "目标目录"}`。显式创建或复用一个同名目录，返回该目录的 ID 和名称；重复名称不能唯一匹配时失败。
  - 普通上传不会自动创建目录。该接口仅在用户指定目录需创建时调用；超时或失败后先 GET 查询结果，再决定后续操作。

- `GET /admin/api/artifacts/group-folders?group_id=<群号>`
  - 仅接受本机请求，返回 `group_id` 和 `folders`；每项只有 `folder_id`、`folder_name`，不返回文件列表或成员资料。
  - 查询上限 30 秒；目录查询失败会明确返回错误，不修改群文件。
- `POST /admin/api/artifacts/publish-local`
  - 固定监听 `127.0.0.1:8080`，只接受本机请求。
  - 校验请求时间、Git 上下文、文件路径和发布元数据。
  - `sha256` 校验 zip 文件本身。
  - `content_sha256` 只作为客户端声明的 zip 内容 hash；服务端会独立读取 zip 条目并计算内容 hash，不信任时间戳，也不只信任客户端传值。
  - 服务端内容 hash 与自身缓存一致时，直接跳过删除、上传和群消息。
  - 通过当前 AstrBot `aiocqhttp` OneBot 连接上传群文件。
  - 同一次请求向同一群上传多个变化文件时，先上传所有文件，最后只引用最后一个文件消息并发送一次发布说明。
  - 发布说明依次显示「分支 短提交号」、提交标题和逐条编号的正文，行间不加空行。正文取文件 `message`，为空时取 `commit_detail`；忽略空行并统一列表编号，保留原有顺序和内容。

文件条目可增加 `folder_id` 字符串：省略、空白或 `/` 上传到群文件最外层，其他值为已有文件夹 ID。ID 来自该群 `get_group_root_files` 响应的 `folders[].folder_id`，不是显示名称。插件在任何删除、上传前核对全部指定文件夹是否属于目标群；不存在或不可访问时失败，不回退根目录，不自动创建文件夹。

同一个文件条目的 `folder_id` 适用于该条目的所有 `targets`；若多个群使用不同的目录 ID，分别填写多个文件条目，每个条目只指定对应群。

上传、同名文件清理和内容去重都按群、目录、文件名隔离。`uploaded`、`skipped`、`deleted` 条目均返回 `folder_id`（根目录为 `""`）。只有选定目录中的同名旧文件参与清理；改目录不会移动或删除原目录文件。根目录沿用旧 `local_artifacts/<group>/<name-hash>.json`，子目录使用 `local_artifacts/<group>/folders/<folder-id-hash>/<name-hash>.json`。子目录上传如果没有返回文件消息 ID，不凭同名历史消息生成引用，避免引用其他目录的旧文件。

## 一代模组同步

`POST /admin/api/artifacts/shapez1-mods` 由 ShapezToolkit 的 `mods update` / `mods publish` 调用，只接受本机请求。目标固定为群 `1163635014` 的现有文件夹 `s1-MOD-官方模组网站`，按名称唯一解析，不创建目录或回退群根目录。

当前包请求包含 `id`（模组 ID）、`file_id`（mod.io 文件 ID）、`path`、`name`（模组名_版本.zip）和 `sha256`；文件必须位于 `D:/project/shapez/ShapezToolkit/shapez1_mods/data/downloads`，最大 64 MiB。废弃请求为 `{"id": 模组ID, "retired": true}`。成功响应包含 `ok`、模组和目标标识、`uploaded`、`skipped`、`deleted` 数量。

`shapez_mods.ShapezModPublisher` 独立核对本地文件哈希，并保存按账号、群、文件夹和模组 ID 隔离的 `shapez1_mods` 状态。每次查询显式读取最多 10000 个目录项，达到上限则停止。NapCat 的列表文件 ID 是临时缓存值，长期记录使用名称、大小、上传时间及上传账号组成的唯一特征。上传前保存目录基线并核对本地 SHA-256，将已校验的字节交给协议端；取得上传成功回执后，新版须唯一匹配新增条目的名称、大小和上传账号，之后才删除已跟踪的旧文件。删除使用当前查询的临时 ID，并重新查询确认结果；首次不会接管人工文件。上传不确定时保留 pending；有成功回执时重跑继续确认，没有成功回执时须核对现场，不能盲目重传。删除失败保留待删除记录。插件不发送额外公告，现有构建发布接口保持独立。

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
