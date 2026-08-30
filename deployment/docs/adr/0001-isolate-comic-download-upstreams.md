# ADR-0001：隔离持续更新的漫画下载上游

状态：Accepted

日期：2026-04-01

## 背景

QQBot 需要组合 JMComic-Crawler-Python 的漫画下载能力和图片转 PDF 能力。JMComic 是持续更新的正式 Python 包，公开 API、配置 DSL、客户端实现和实体类型仍可能变化；salikx/image2pdf 则是带硬编码配置路径的单文件脚本，不是稳定库接口。

AstrBot Core 由本 fork 的源码和项目内 `.venv` 管理，本地插件直接位于 `data/plugins/`。直接复制上游源码、跟随未锁定 latest，或让上游实体进入 main.py，都会使更新不可复现并扩大兼容修改范围。

## 决策

1. 运行时固定 jmcomic==2.7.2、img2pdf==0.6.3 和 pikepdf==10.11.0，版本清单位于 `deployment/extra-requirements.txt`。
2. AstrBot 更新脚本在 Core 依赖同步后，将清单安装到项目自己的 `.venv`。日常使用 `scripts/start.ps1` 明确同步依赖，Core 启动阶段使用 `uv run --no-sync`，不会隐式改变已安装集合。
3. 只有 comic_pdf/adapter.py 可以导入 jmcomic。适配器启动时校验精确版本和必需公开入口，并把结果转换为本插件的 DownloadedComic、ComicChapter 等类型。
4. image2pdf 仓库只作为输入格式和自然排序行为参考，不作为运行依赖，也不复制其硬编码脚本。PDF 输出由本插件 PdfRenderer 封装成熟 img2pdf 包。
5. 上游升级必须显式修改版本清单和适配器，先完成允许的编译/LSP 与静态兼容检查；真实作品下载、缓存、PDF 加密和 OneBot 私聊上传验证只在部署者明确授权运行时验收后执行。
6. 下载图片、构建中间产物和每次发送的 AES 加密副本只使用 AstrBot Core temp 下的独立 job 目录并在任务结束后清理。标准未加密 PDF 按 JMID 持久缓存于 qqbot_features_runtime/comic_pdf_cache，每目录用 metadata.json 记录完整状态和逐文件 SHA-256，默认受 10 GiB LRU 上限约束。
7. 相同 JMID 的并发请求共享一个下载任务；不同 JMID 最多并发 2 个，其余进入有界 FIFO 队列。命令层只检查当前云栖实例的好友能力，最终文件和密码只由云栖私聊发送。

## 结果

- 命令、权限、OneBot 发送和清理策略不依赖 JMComic 内部对象。
- 上游升级需要一次显式仓库改动，但可以通过固定测试和真实探针验证，避免运行中被 latest 破坏。
- 不自动获得上游新功能；需要在适配器内有选择地接入。
- PDF 编码和加密各增加一个固定依赖，但比 Pillow 一次性持有大量页面更适合大作品，并由自有接口保持可替换。
- 缓存避免重复下载并允许每次交付重新加密；代价是本机运行态持久保存未加密 PDF，因此必须维持目录边界、完整性校验和容量淘汰。

## 被否决方案

- 直接 vendoring 两个上游：会复制持续更新代码并增加许可证、同步和安全补丁维护成本。
- 每次启动安装 GitHub latest：启动依赖网络且无法复现，接口变化会直接中断机器人。
- 直接调用 JMComic CLI：参数和输出文本不是本 bot 的稳定协议，也难以落实任务目录、资源限制和结构化错误。
- 直接复用 JMComic 内部 img2pdf 插件：会把插件钩子、命名和删除语义耦合到上游，无法完整执行本 bot 的分卷与上传生命周期。
