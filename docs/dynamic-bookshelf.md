# 动态书架设计与验收要求

状态：待用户验收，用户验收前不得合入 main。基线：275b04b。

## 目标与范围

在现有本地单用户阅读统计之外增加书架视图。保留 Python 3.11+ 标准库与原生 JS/CSS，无新增运行依赖。默认打开书架；用户可切换阅读统计，原有统计、演示、导出不回归。

书架展示最近阅读（最多 4 本）与完整封面墙，支持本地书名/作者搜索、最近阅读/书名/作者排序、分类/类型/已读完筛选，条件组合生效并可重置。localStorage 仅保存浏览偏好，禁用时正常运行。全部列表加载到浏览器内存，排序筛选搜索不调用任何数据接口；图片仅在实际需要时请求。

书架总条目必须含 books、albums 和非空 mp；有声书的内容完结不能作为用户已读完。文章收藏是单独的入口说明，不编造其文章内容。未知进度、笔记数量不得显示为零。最近阅读按已返回的时间排序，不推断加入时间或未读状态。

## 同步与存储

首次进入书架先 GET 本地缓存并立即展示，再后台自动 POST 同步一次。切换视图不会反复自动同步；刷新页面会重新同步。手动按钮只同步书架，不重拉十二个月统计。进行中按钮禁用、请求合并；排序筛选期间不重新同步。

SQLite 保存最新完整书架快照与逐本详情/进度、完整笔记概览，分别记录成功时间。同步先校验再原子替换；合法空列表清空，缺少数组/格式错误/业务错误/upgrade_info 保留旧快照。详情和进度独立失败独立保留，返回局部错误；缓存先显示再按需更新。每次书架同步后只补最近最多 4 本电子书进度，不逐本抓取全架。无缓存失败显示重试，有缓存失败保留内容并提示时间。

按 API key 的后端不可逆指纹隔离账号命名空间，不向客户端暴露指纹或密钥。密钥变化不能读取旧账号书架、详情、笔记、封面。保留现有统计缓存兼容性。演示全程不读取密钥、不读取真实缓存、不访问上游。仅将必要字段发送浏览器，绝不发送完整原始响应。

封面存 `.local/covers/`（可按账号再分层），响应为同源图片；浏览器使用原生 lazy loading。上游 URL 改变缓存键改变。只允许 HTTPS 的实测微信读书封面域名，不接受客户端提供 URL，不跟随重定向，限制类型、长度、超时。并发同一图片只下载一次，失败显示占位图且可后续重试。演示生成本地 SVG 封面，无外部请求。不暴露任意文件路径。

## 本地 HTTP 接口约定

所有接口沿用 Host/Origin/Fetch Metadata 校验；POST 必须 `X-WeRead-Client: dashboard`。JSON 错误 `{error: 中文信息}`。参数使用 URL query，标识必须经 URL 编码。

- `GET /api/shelf`：只读缓存，`{items: [], syncedAt: null, demo: false, notesSyncedAt: null}`。
- `POST /api/shelf/sync`：同步列表，返回与 GET 相同结构，不与月度统计绑定。
- `GET /api/book?id=book:123`：只读单本缓存，`{id, info: null|{}, progress: null|{}, notes: null|{}, infoSyncedAt: null, progressSyncedAt: null, notesSyncedAt: null, errors: []}`。
- `POST /api/book/sync?id=book:123&part=all`：获取详情和进度；`part=progress` 只取进度。返回与 GET 相同结构，局部失败 errors 为中文字符串数组；全部失败时也保留缓存并明确报告。只允许当前书架中的电子书，不提供任意 bookId 网关代理。同本并发合并/串行后复用；详情缓存 15 分钟、进度缓存 5 分钟，`force=1` 可强制更新。
- `POST /api/notes/sync`：独立完整分页同步笔记概览，使用顶层 count/lastSort，验证游标前进；失败不能覆盖旧概览。返回 `{syncedAt, bookCount}`。用户可在详情中主动触发，不能阻塞书架同步。
- `GET /api/cover?id=book:123`：只解析已同步条目的封面。返回已缓存图片；未缓存时安全下载；没有或下载失败返回 404，前端显示占位。

每个 item 固定字段：`id`（`book:<bookId>` / `album:<albumId>` / `articles`）、`kind`（book/album/articles）、`bookId`（非电子书 null）、`title`、`author`、`category`（字符串，缺失为“未分类”）、`coverPath`（本地路由或 null）、`readerLink`、`deepLink`、`readUpdateTime`（秒或 null）、`finished`（bool 或 null）、`progress`（缓存进度对象或 null）。

info 白名单：title/author/intro/publisher/publishTime/wordCount/newRating/newRatingCount/readerLink/deepLink。newRating 保留上游原值，展示为“微信读书推荐值”，原值除以 10 得到百分数（765 → 76.5%），未知或 0 显示暂无推荐值。
progress 白名单：progress（0–100 整数，1 表示 1%）、chapterUid、chapterOffset、updateTime、recordReadingTime、finishTime（有值才返回）。
notes：`{noteCount, reviewCount, bookmarkCount, total}`，total 为前三者之和；完整概览没有该书才可显示 0，未同步为 null。
跳转只使用上游 readerLink/deepLink，必须校验 HTTPS 或已知 weread scheme，拒绝 javascript 等主动内容。未知链接不展示。

## 详情与动效

点击封面立即打开详情，先用条目信息和缓存填充，再加载缺失/过期信息。简介、推荐值、阅读百分比、笔记数量分区；未知/错误分别展示，笔记有独立同步入口。有声书与文章入口只显示已知元信息和能力边界。

验收中实测的口径修正：网关 newRating=765，对照[微信读书官方详情页](https://weread.qq.com/book-detail?type=1&v=0c8322b0813aba6dfg0163e5)显示推荐值 76.5%。此处采用已核对的十分之一换算，修正安装的 skill 对评分单位的描述。recordReadingTime 与 readingTime 的实际返回和本地说明存在口径差异，第一版不展示单书累计时长，也不凭字段名推断替代字段；现有阅读统计时长不受影响。

桌面双栏面板，封面通过 FLIP 或 Web Animations 从点击位置移动放大至左栏；关闭回原位。手机底部展开面板。250–350ms，遮罩淡入，减少动态效果时简单淡入。网络不参与动画时序。

使用原生 dialog 或完整等效的焦点管理；支持按钮、遮罩、Esc 关闭，焦点返回触发项，保留排序筛选及滚动位置。同步时不重排正在浏览的可见书架造成跳跃；可保存锚点/滚动位置。打开的书被移出时保持可关闭详情，回退焦点到书架标题。快速开关/异步返回不能把另一书的信息写入当前面板；动画清理、滚动锁正确。

## 验证与交付

开发 agent 先补关键失败检查再实现；测试 agent 独立按此要求检查，不能仅复述开发者报告。root 负责代码审查、完整命令验证与真实浏览器最终验收。

必须验证：缓存先显示、每页仅一次自动同步、手动同步、有效空架、畸形响应保留、业务/升级错误保留、账号隔离、重复请求合并、进度 1%/100%/未知、有声书完结口径、notes 分页与中断、封面安全/命中/更新/失败、筛选零数据请求、localStorage 禁用、恶意书名转义、快速开关、Esc/焦点/滚动、桌面/窄屏/减少动画、演示完全隔离、原有统计回归。

运行 `python3 -m unittest discover -s tests -v`、`node --check web/app.js`、`node --check web/shelf.js`、`node tests/frontend.cjs`，新增书架前端离线测试纳入 CI。真实浏览器检查不能用 DOM stub 替代。仅演示截图可提交，真实数据和密钥不得提交。

交付须包含 README 使用与缓存说明、验收记录、任务分支提交、测试结果和本地预览地址。用户验收前禁止合并、部署。
