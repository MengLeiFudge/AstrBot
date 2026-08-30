# 棉花糖功能合集

作者：MengLei

## 插件用途

本插件是 AstrBot 当前固定功能入口，覆盖群务、菜单、生图、美图、表情管理、复读、养鲲、落樱之都、Arcaea、JM 漫画 PDF、Factorio 和异形工厂。本插件不拥有 Poke 逻辑：拍一拍不在这里生成特殊回复或专属文案，Poke 由 `astrbot_plugin_topic_concentration` 的拍一拍状态机处理，完整行为合同见 `../astrbot_plugin_topic_concentration/README.md`。

固定指令统一使用同一套触发规则：群聊和私聊都可触发；群聊可以 @ 当前 bot 后发送，也可以不 @ 直接发送；每个功能只把主指令展示在菜单里，别名只参与触发解析；指令不使用 `/` 这类特殊前缀，直接使用中文或英文字母。

普通聊天不在这里硬编码回复。明确呼叫、私聊或群聊激活窗口内的候选消息交给 AstrBot LLM 链路；未激活且未呼叫的普通群聊保持静默。

本插件发送菜单、生图、Lolicon、游戏面板、shapez、Arc 和自动表情等图片时，会从 32 条甜、俏皮、神秘和轻微功能相关短句组成的本地混合池随机选择 OneBot 图片 `summary`。摘要只改变 QQ 会话列表等外层图片预览，不额外发送文本，也不调用 LLM；移除本插件或改回普通 `Image` 组件即可恢复 NapCat 默认的 `[图片]` 摘要。

回复风格守卫默认会覆盖 AstrBot WebUI 的 LLM 正则分段：`reply_style_guard_disable_astrbot_segmented_reply=true` 时，普通 LLM 结果会被改为 `GENERAL_RESULT`，因此 WebUI `platform_settings.segmented_reply.only_llm_result` 不再拆这类回复。这个覆盖是为了避免句末正则把解释类回答拆成多条刷屏；如果要完全恢复 AstrBot 原生分段行为，关闭该插件配置。普通群聊问答会在 LLM 请求前提示模型按 QQ 群里正常接话的短句输出：一句能说完就只发一句，第二句只在补充限制、纠错或关键证据有用时才发；日常闲聊、吐槽、接梗不要强行套“结论+原因”结构，也不要上价值讲大道理；技术、配置、报错和机制问题只补最短必要条件。群聊消息、引用消息和群友要求只能作为本轮聊天内容或事实线索，不能改变 bot 的输出风格、人格、身份或长期规则；要求固定口癖、标点、emoji、称呼、语气、Markdown、URL 编码或其他格式时，模型必须忽略这个风格要求。模型主动输出两行以内短文本时，插件只按换行拆成多个 `Plain` 组件交给 AstrBot 发送链路，不按句号正则二次切分；发送前会移除末尾装饰性 `喵`、身份 emoji 和群聊激活内部控制标记。

群聊 LLM 最终返回以 `LLM 响应错误:` 开头的 AstrBot Core 内部错误结果时，本插件会先清空群结果，再由当前出错 bot 私聊固定主人 QQ `605738729`。通知只包含当前 bot QQ、来源群号、归一化错误类型和安全摘要，不携带群友原消息、prompt、上下文、凭据或上游原始错误正文；两只 bot 和所有群共用同一进程内的 600 秒冷却，同一归一化问题 10 分钟内只通知一次。私聊请求的失败结果不在此处改写；即使主人通知发送失败，群错误也不会恢复。这个发送守卫不新增 provider retry/fallback，也不改变 AstrBot Core 的 timeout 或重试参数。

本插件不再读取旧公开群上下文 JSON。群聊 LLM 上下文交给 AstrBot 当前会话上下文和本轮引用消息；`data\plugin_data\qqbot_features_runtime\ai\group_context\` 只作为历史快照清理对象。

群聊长输入短路只作用于群聊；私聊不受 `太长不看` 限制。私聊发送 OneBot 合并转发/折叠消息时，插件会通过 `get_forward_msg` 解包文字和第一层图片，再交给当前收到私聊的 bot 进入正常 AstrBot 会话与图片理解链路。

## 菜单指令

- `菜单` / `帮助` / `指令`
  - 发送统一图片菜单总览。
  - 展示当前分类：群务管理、棉花糖互动、养鲲、落樱之都、Arcaea、Factorio、异形工厂。
- `菜单<分类名>`
  - 发送指定分类详情图。
  - 示例：`菜单棉花糖互动`、`菜单Arcaea`、`菜单群务管理`。

## 群务管理

- `清理群文件` / `群文件清理通知`
  - 作者或机器人自身限定。
  - 扫描超过一周的外层群文件并通知处理。
- 好友申请
  - 按配置自动同意 OneBot 好友申请。
- 邀请入群
  - 按配置自动同意 OneBot 邀请入群请求。
  - 机器人自身入群成功后优先私聊通知邀请者，文案包含群名和群号。
- 新成员入群欢迎
  - 云栖随机选择以“群地位”开头、表达群地位变量减 1 的完整表达式欢迎新成员。
  - 夜凛、星遥和月澄等已知机器人账号不会触发欢迎。

## 棉花糖互动

- `棉花糖生图 <提示词>`
  - 提交 RightCodes 生图任务。
  - 使用当前 QQ 已保存的生图模型，从第一张开始按模型价格扣分；不支持在生图命令内临时指定模型。
  - 初始默认模型是 `gpt-image-2`，模型选择按用户 QQ 跨群共用。
  - 提示词包含“仿照上面、这张图、参考、聊天记录”等上下文指代，或引用了图片时，会先用当前会话 AstrBot provider 整理成准确生图提示词，再扣积分调用 RightCodes。
  - 如果只有 `[图片]` 这类占位、没有可用引用图片 URL/路径或引用文本，插件会直接提示补充引用或写完整提示词，不扣积分。
  - 生图调用当前官方异步协议：向 `https://www.rightapi.ai/draw/v1/images/generations` 提交 `async=true` 任务，再轮询站点级 `/v1/tasks/{task_id}` 取得图片。
  - 生图成功、失败或超时失败都会引用原始生图请求；默认 240 秒总超时，失败后退回本次扣除的积分，并提示模型查看和切换指令。
  - “生成一张 xxx 图片”这类自然语言请求只提示生图指令和积分消耗，不直接执行扣费生图。
- RightCodes 生图接口知识库
  - 用户询问 RightCodes 画图接口、`body`、`size`、`imageSize`、`async`、`/v1/images/generations`、`generateContent` 或 `/v1/tasks/{task_id}` 时，会在 LLM 请求前注入官方接口资料。
  - 如果用户引用上一条问题后只说“回答一下”，被引用消息会作为当前请求原文参与 RightCodes 知识库判定和 LLM 上下文，不只看当前短句。
  - 当前协议固定异步提交并轮询任务；Images 接口的 `size` 支持比例或像素串，`imageSize` 支持 1K、2K、4K。
- `生图模型` / `生图价格`
  - 查看当前模型、可用模型、价格、积分消耗和上游分辨率说明。
  - 默认倍率 1000 下：`gpt-image-2` 40、`gpt-image-2-vip` 130、`nano-banana-2-lite` 50、`nano-banana-pro` 180 积分/次；仅展示本次真实调用成功并下载到有效图片的模型。
- `切换生图模型 <模型名>`
  - 持久切换当前 QQ 的生图模型；`生图模型 <模型名>` 是不进菜单的别名。
  - `切换生图模型nano-banana-2-lite`、`切换生图模型 nano-banana-2-lite` 和 `切换 生图 模型 nano-banana-2-lite` 都能匹配。
- `查看积分` / `balance` / `points`
  - 查询当前 QQ 的积分、当前模型和该模型单次积分消耗，不展示历史累计消息数。
  - 回复末尾提示 `生图模型` 和主切换指令 `切换生图模型 <模型名>`，不展示隐藏别名。
- `积分排行` / `积分排行榜`
  - 按跨群累计积分输出全部用户中积分最高的前 10 名；同分时按 QQ 号稳定排序。
  - 每条群消息缓存当前群的群名片、QQ 昵称和时间；排行优先用当前群群名片、其次当前群 QQ 昵称，当前群没有时只使用其他群最新 QQ 昵称。
  - 仍没有昵称时显示中间位星号脱敏的 QQ，不使用其他群群名片。
- `用量`
  - 发送两张图片：第一张按账号依次展示 5h / 7d 额度卡和该账号自己的当前 7d 周期用户消费榜，全部账号区块结束后展示全账号当日 / 本周 / 30d 消费榜；第二张展示 CodexRadar 社区公开的智力效率榜，包括各模型档位的 IQ、平均费用、平均耗时和近 24 小时有效作答数。
  - 每个账号榜的窗口起点为该账号原始 `seven_day.resets_at - 7 days`，按稳定 `account_id` 过滤：起点当天向下取整到所在小时后汇总小时趋势（例如 09:10 从 09:00 桶开始），后续日期按自然日汇总 `actual_cost`；不同账号不再合计，每个榜显示该账号全部非零用户并按金额降序。底部全账号榜使用 Sub2API `actual_cost` 和固定 `Asia/Shanghai` 时区：当日 / 本周 / 30d 以同一次后台刷新时刻为终点；当日起点为最近已到达的 08:00（08:00 前回退到前一天 08:00），本周起点为最近已到达的周一 08:00（周一 08:00 前回退到上周一 08:00），30d 起点等于当日起点再减 30 个日历日；起点当天从该整点小时桶开始汇总小时趋势并包含当前小时桶，后续日期按自然日汇总。
  - 账号和用户由插件自动分页发现；用户显示名优先使用 username，为空时展示等长脱敏邮箱；底部三档业务周期消费全部为 0 的用户不进入全账号榜。
  - 底部用户榜和 Sub2API `source=active&force=true` 账号刷新各自默认每 300 秒一次，错开半个周期；各账号 7d 周期榜跟随账号刷新并共享本轮结束时刻。CodexRadar 智力效率公开数据独立每 300 秒刷新并渲染为本地缓存图片。群里发送 `用量` 时只读取缓存，不发起 Sub2API 或 CodexRadar 请求；CodexRadar 刷新失败时保留上次成功图片，首次刷新尚未成功时只发送原 Sub2API 用量图。账号列表或底部用户榜刷新失败时保留上次成功缓存；单个账号周期榜失败时只保留该账号自己的上次成功榜并在对应区块显示错误，不阻止其他账号更新。
  - 上游用户消费接口单次最多返回 200 人；超过时会明确报错，不会把未返回用户的消费当作零。
  - 可配置一个或多个提醒群号；5h 用量首次跨过 80%、90%、95% 时自动提醒，回落到阈值以下后才会再次触发同一阈值。
- `来点美图` / `色图` / `混合`
  - 调用 Lolicon 图片能力；元数据和群配置使用 AstrBot 迁移后的数据库，图片直接使用远程 URL，不再保存到本地缓存。
- `开群色图` / `关群色图`
  - 作者限定，控制当前群 R18 权限。
- `开图片显示` / `关图片显示`
  - 作者限定，控制 R18 结果是否直接发图。
- 复读
  - 群里连续出现相同纯文本消息时概率复读，并带冷却。
- 表情管理
  - `表情管理`
    - 查看当前图库分类。
  - `表情管理 开启管理后台`
    - 主人或机器人自身限定，私聊启动本地图库 WebUI。
  - `表情管理 添加表情 [类别]`
    - 主人或机器人自身限定，进入 30 秒图片上传等待状态。
  - `表情管理 清空指定类型 [类别]` / `表情管理 删除类型本身 [类别]` / `表情管理 清空全部`
    - 主人或机器人自身限定，执行前需要同一发送者二次确认。
  - 本地图片和索引继续使用 `data\plugin_data\meme_manager\`；配置入口在本插件配置里使用 `meme_manager_` 前缀，不再读取旧 `meme_manager_config.json`。
  - 普通 LLM 附表情不要求 WebUI 依赖；上传图片需要 `aiohttp` 和 `pillow`，管理后台需要 `quart` 和 `hypercorn`，Cloudflare R2 图床同步需要 `boto3` 和 `botocore`。

## 养鲲

- `摸鲲` / `养鲲` / `抓鲲` / `捕鲲`
  - 创建或获取当前用户的鲲。
- `属性` / `背包` / `商城` / `签到`
  - 查询或操作当前用户存档。
- `等级排行` / `财富排行` / `萌泪币排行`
  - 查看排行榜。
- `挑战` / `进击...` / `boss`
  - 参与战斗玩法。
- `赠送...` / `赠送全部...`
  - 用户间道具或资产转移。

## 落樱之都

- `落樱之都`
  - 查看基础玩法菜单。
- `注册<名字>` / `改名<名字>`
  - 创建或修改角色名。
- `个人信息`
  - 查看当前角色状态。
- `加经验<number>` / `嘤<number>`
  - 基础数值操作。
- `加<number>力量|智力|体质|敏捷|魅力`
  - 角色加点。
- `恢复` / `回复`
  - 恢复当前角色。

## Arcaea

- `arctj10.5`
  - 按 PTT 推荐谱面。
- `archd` / `arctz`
  - 查询当前活动梯子。
- `zm` / `arczm`
  - 开始字母猜歌。
- `qh` / `arcqh`
  - 开始或继续曲绘猜歌。
- `arcqh bt` / `arcqh 补图`
  - 打开下一块曲绘。
- `jx` / `arcjx`
  - 揭晓当前猜歌局。
- `xz` / `arcxz`
  - 作者限定，查询并下载 Arcaea 相关安装包。

## JM 漫画 PDF

- `JM1218951` / `jm1218951` / `JM 1218951`
  - 任何用户都可在群聊或私聊发送完整命令；普通正文中的 JM 数字不会触发。云栖必须已经是请求者好友。
  - 原会话使用不带引用的普通消息回复好友检查和任务状态。缓存命中时直接提示开始处理，不给预估时间；开始下载或排队时按队列位置和并发批次给出粗略完成时间。
  - 最终交付只通过私聊发送。加密和切片完成后，先告知作品 ID、标题、作者、标签、切片总数和统一密码，再按顺序发送全部 PDF 切片，最后发送 `JM作品ID发送完成`；整个 JM 流程不使用引用消息。
  - PDF 密码是作品 ID 的完整数字部分，例如 `JM1000` 的密码是 `1000`。持久缓存保存未加密标准 PDF；每次交付在 Core temp 生成 AES 加密副本，发送后只删除临时副本。
  - 使用锁定版本的 `jmcomic` 下载整本，按上游章节顺序和自然页序生成 PDF，不保存 cookie。相同 JMID 只下载一次，不同 JMID 默认最多并发 2 个，其余最多 50 个 FIFO 排队；同一 QQ 可以连续提交多个作品。
  - 缓存目录为 `qqbot_features_runtime\comic_pdf_cache\JM<作品ID>-【作者】标题\`。目录内 `metadata.json` 记录完整状态、作者、标题、标签、页数、大小、版本和逐 PDF SHA-256；多卷使用 `(1)`、`(2)` 后缀。默认缓存上限 10 GiB，超限按最后访问时间淘汰。
  - 默认单个 PDF 最多 500 页、100 MiB；整本超限时按章节分卷，单章仍超限时继续按页拆分。
  - `image2pdf` 上游仓库仅作为排序和转换行为参考；运行时使用本插件自有 `PdfRenderer`、锁定的 `img2pdf` 编码依赖和 `pikepdf` AES 加密依赖。

## Factorio

- `Factorio下载链接` / `异星下载链接` / `太空时代下载链接`
  - 获取 Factorio Space Age Windows 安装包下载链接。
  - 需要本机配置 Factorio 凭据。

## 源码知识兜底

- LLM 请求前按当前问题检索只读源码树，临时注入少量证据片段；不依赖 AstrBot 原生知识库或 Embedding。
- 默认领域覆盖 DSPCore、万物分馏、MLJ_DSPmods 辅助模组/工具、星环、创世之书、shapez 和 Factorio。
- `dsp-mod-tools` 辅助模组/工具域默认覆盖 SaveDataExporter、UXAEnhance、AfterBuildEvent、GetDspData、VanillaCurveSim 和 UXAssist。
- 群号只作为默认领域偏置；当问题包含精确模组名、工具名、目录名或机制词时，会跨默认群域检索对应源码根。
- 源码知识默认按低成本注入：`source_knowledge_max_results=4`、`source_knowledge_max_chars=2600`、`source_knowledge_max_files_per_domain=80`、`source_knowledge_max_file_bytes=220000`；复杂技术追查需要大文件证据时，再在运行态配置里临时调高。

## 异形工厂

- `i <短代码>` / `view <短代码>`
  - 渲染 shapez 短代码图片。
- `chart <短代码>`
  - 渲染结构图。
- `path <短代码>`
  - 渲染路径图。
- `p <参数>` / `puzzle <参数>`
  - 在线谜题入口；未配置 shapez token 时提示无法获取。

## 配置项

- `auto_approve_friend_requests`
  - 是否自动同意好友申请，默认开启。
- `auto_approve_group_invites`
  - 是否自动同意邀请入群，默认开启。
- `sub2api_base_url`
  - Sub2API 根地址，例如 `https://ai.example.com`。插件会显式直连该地址，不继承 Windows WinINET 或 urllib 系统代理。
- `sub2api_admin_api_key`
  - Sub2API 设置页生成的 `admin-` 开头 Admin API Key，只填写在运行态插件配置，不写入源码或示例配置。
- `sub2api_timeout_seconds`
  - Sub2API 查询超时秒数，默认 90 秒；账号额度使用 `source=active&force=true` 主动刷新，用户榜与账号刷新错开半个周期。
- `sub2api_refresh_interval_seconds`
  - Sub2API 后台刷新间隔秒数，默认 300 秒；最低按 60 秒处理。
- `sub2api_alert_group_ids`
  - Sub2API 5h 用量提醒目标 QQ 群号，英文逗号分隔；留空则不主动提醒。
- `reply_style_guard_disable_astrbot_segmented_reply`
  - 默认开启，表示插件故意架空 AstrBot WebUI 对 LLM 结果的句末正则分段。
  - 关闭后恢复 AstrBot 原生 `platform_settings.segmented_reply` 行为。
  - 普通群聊问答的“分段”优先由 LLM 自己输出一到两行短气泡；插件只拆模型明确给出的短行，不做二次 LLM 分段。
- `reply_style_guard_long_reply_fold_threshold_chars`
  - 默认 300。群聊 LLM 纯文本回复超过该字符数时，插件会先改写为 AstrBot `Nodes/Node` 合并转发消息链，再交回 AstrBot 发送链路。
  - 该阈值独立于 Core `forward_threshold`，用于更早折叠水群长回复；填 0 禁用插件折叠。
- `reply_style_guard_long_input_tldr_threshold_chars`
  - 默认 300。群聊中直接 @ 或唤醒当前 bot，正文非空白字符数超过该值时，本地回复 `reply_style_guard_long_input_tldr_text`，不进入 LLM。
  - 只限制群聊；私聊不限制。固定命令、生图、群管、下载、积分等副作用入口不会被这个长输入短路吞掉。
- `reply_style_guard_long_input_tldr_text`
  - 默认 `太长不看喵`。
- `jmcomic_enabled`
  - 默认开启。关闭后 `JM作品ID` 命令不执行下载。
- `jmcomic_proxy`
  - 可选 HTTP/HTTPS 代理地址；留空时显式禁用 JMComic 的系统代理继承，不保存 cookie。
- `jmcomic_timeout_seconds`
  - 单作品下载超时，默认 1800 秒，范围 60-7200。
- `jmcomic_max_pages_per_pdf` / `jmcomic_max_pdf_size_mb`
  - 单个 PDF 默认最多 500 页、100 MiB；超限时按章节和页数继续拆分。
- `jmcomic_max_concurrent_jobs`
  - 默认 2，范围 1-2；限制不同 JMID 的并发下载，相同 JMID 自动共享一个任务。
- `jmcomic_max_queued_jobs`
  - 默认 50，范围 1-100；并发槽占满后的 FIFO 队列上限，同一 QQ 可连续提交多个作品。
- `jmcomic_cache_max_gb`
  - 默认 10 GiB，范围 1-100 GiB；超限按 `metadata.json` 的最后访问时间淘汰。
- `source_knowledge_max_results` / `source_knowledge_max_chars`
  - 默认 `4` / `2600`。源码知识按低成本运行，需要追查大文件或更完整源码证据时再临时调高。
- `meme_manager_webui_port`
  - 表情管理后台端口，默认 5000；后台只通过 `表情管理 开启管理后台` 启动。
- `meme_manager_enable_mixed_message`
  - 默认开启；开启后表情图片可与文本混合在同一条消息链。
- `meme_manager_emotions_probability` / `meme_manager_mixed_message_probability`
  - 控制自动附表情概率和混合图文概率，取值 0-100。
- `meme_manager_image_host` / `meme_manager_image_host_config`
  - 可选图床同步配置，支持 Stardots 和 Cloudflare R2。

## 单账号边界

- 当前 AstrBot 账号只有云栖 `1443944862`；主人账号为 `605738729`。
- 夜凛 `2629227874`、星遥 `3056830689`、月澄 `3109326090` 只作为静态姐妹关系和机器人防回环事实，不参与 AstrBot worker 或固定命令路由。
- 已知姐妹机器人发出的消息不会触发本插件固定命令或普通回复。
- 生图积分、养鲲、落樱、Arcaea 会话等用户数据按用户 QQ 保存。
- 菜单、生图、群务等固定命令由云栖直接执行，不做任何跨账号协调。
- 闲聊、普通问答、显式呼叫和群聊激活窗口内的候选消息交给 AstrBot LLM 链路；仅 @ 云栖视为显式呼叫，拍一拍云栖走拍一拍状态机（合同见 `../astrbot_plugin_topic_concentration/README.md`）。
- 普通 LLM 请求如果带引用消息或聊天记录，本插件会把当前消息与完整来源树作为本轮临时上下文：外层引用使用 `Reply.sender_id`，`Node/Nodes` 和通过 `get_forward_msg` 有界展开的嵌套转发逐条保留发送者 QQ；聊天记录第一层图片会按原始顺序提取并交给 AstrBot 原生图片理解链路，单次最多 12 张，嵌套转发图片只在剩余额度内继续读取。

## 数据与安全边界

- 使用 `data\plugin_data\qqbot_features_runtime` 作为游戏、Arcaea、RightCodes 积分和本地 artifact 发布状态目录；游戏、Arcaea 会话/缓存、复读/thunder/Lolicon 群配置、Shapez 群文件清理状态和 RightCodes 积分优先写入 `db\qqbot_features.sqlite3`。
- JM 下载图片、构建中间产物和每次发送的加密 PDF 副本只写入 AstrBot Core temp 下的 `qqbot_features\jmcomic\`，完成、失败或超时后清理。未加密标准 PDF 持久保存在 `qqbot_features_runtime\comic_pdf_cache\JM<作品ID>-【作者】标题\`；每目录只有 `metadata.json` 和一个或多个校验过的 PDF，默认受 10 GiB LRU 上限约束。
- Lolicon 元数据写入 `db\lolicon.sqlite3`，图片不再下载到本地；菜单图、Arc 猜歌面板、shapez 渲染图和临时面板写入 AstrBot Core 的 `data\temp\qqbot_features\` 子目录，进入 Core `temp_dir_max_size` 容量清理范围。插件后台只删除超过安全窗口的重复图片副本，不做独立按日期清理；旧 AI 记忆、TTS、头像和 shapez 静态旧目录不再作为日常运行态保留。
- 使用 `data\plugin_data\meme_manager` 作为本地表情包运行态目录；这是兼容保留的数据路径，不再对应独立 AstrBot 插件。
- 旧公开群上下文快照不再作为 prompt 事实源，也不提供群聊记录导出命令。
- 不提交运行态数据、QQ 登录态、token、数据库或日志。
- RightCodes API Key 直接填写在本插件配置字段 `api_key`，不写入插件源码，也不再读取旧 `.env`。
- Sub2API Admin API Key 直接填写在本插件运行态配置字段 `sub2api_admin_api_key`，不写入插件源码、示例配置、群消息或日志。
