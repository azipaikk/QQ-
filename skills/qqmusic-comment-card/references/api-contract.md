# QQ 音乐数据来源与已知情况

本 skill 的数据来自第三方开源库 `qqmusic-api-python`（仓库 l-1124/QQMusicApi，GPL-3.0）。它是**非官方**的：
没有腾讯官方的开放接口提供评论数据。改脚本、升级库版本、排查问题时先看这里。

## 目录
- 这个库在你电脑上会做什么
- 用到的调用和字段
- 一次真实测试的观察
- 评论里常见的"脏数据"
- 尚未验证的点
- 隐私与合规

## 这个库在你电脑上会做什么

- 为了访问 QQ 音乐，它会**模拟一台 Android 设备**：随机生成设备编号，并向腾讯的服务器（`api.tencentmusic.com`）
  注册这台模拟设备，之后再请求歌曲、评论数据。默认不把设备信息保存成文件。
- 不需要登录，不读取浏览器 Cookie，不需要任何账号或 Key。
- 访问的域名：`u.y.qq.com`、`c.y.qq.com`（数据）、`api.tencentmusic.com`（设备注册）、`y.gtimg.cn`（封面图）。
- 要求 Python 3.10+。第三方库及依赖由 `install_deps.py` 装进技能目录的 `.deps/`，不动系统环境，删除该文件夹即卸载。
- 版本固定为 `0.7.3`（选发布满两周以上的稳定版；升级时同样挑发布满 14 天的版本，并重新做一次依赖漏洞审计）。
- 库的作者声明项目仅供技术研究，请勿商用或侵犯版权。GPL-3.0：你公开自己的仓库时只写"需要安装这个库"，
  不要把它的代码复制进你的仓库。

## 用到的调用和字段

```python
async with Client() as client:
    resp = await client.search.search_by_type(keyword, num=10)       # resp.song → 歌曲列表
    # 每首：id、mid、title/name、singer[].name、album.name、album.mid、cover_url(size)
    detail = await client.song.get_detail(song_id)                   # detail.track → 同上的歌曲对象
    pages = await client.comment.get_hot_comments(song_id, page_size=15).collect(limit=N)
    # 每页：comments、has_more、total；每条：content、praise_num（点赞）、reply_cnt（回复数）、cmid
    lyric = await client.lyric.get_lyric(song_mid)                   # lyric.lyric → 已解密的 LRC 歌词
```

- 热评不需要登录。每页约 15 条（第一页可能多 1 条）。用 `.collect(limit=页数)` 一次取多页。
- 封面：`song.cover_url(size)`，size 可选 150/300/500/800/1200/1500，由专辑 MID 拼出 `y.gtimg.cn` 上的图片地址。
- 评论条目里还有 `nick`、`avatar`、`encrypt_uin` 等评论者信息：**一律不读取、不保存、不展示**。

## 一次真实测试的观察（《晴天》周杰伦，用户本机运行）

- 搜索第 1 条就是周杰伦原唱（歌曲 ID 97773，专辑《叶惠美》）。
- 封面：300/500/800/1200 都是标称尺寸，请求 1500 实际得到 1477×1477（专辑原图上限）。
- 评论总数 33 万多条；"热门评论"列表 `total` 约 3964 条；连取 4 页得到 61 条，`has_more` 仍为真，可继续翻页。
- 评论比网易云长得多：61 条里 ≤25 字的 10 条，26–50 字 7 条，51–75 字 7 条，超过 75 字 37 条。
- 单条评论的字段：cmid、seq_no、content、pub_time、praise_num、reply_cnt、state、hot_score、rec_score、
  song_id、song_name、singer_names、song_ts_elems、hash_tag_list、little_tails、icon_list、vip_ui、sub_comments。

## 评论里常见的"脏数据"（脚本怎么处理）

| 现象 | 处理 |
|---|---|
| 换行被转义成字面的 `\n` 两个字符 | `normalize_comment` 还原成真换行 |
| 零宽空格、韩文填充符等不可见字符 | 去掉；用它们刷空行的"占位刷屏"评论会打硬标记 |
| Unicode 表情符号（字体里没有） | 去掉，并打软标记"已去除表情符号"，交付时要告诉用户 |
| `[音频]`、`[em]e100[/em]` 之类的代码 | 打硬标记，默认不选 |
| 广告、推广、"点击链接" | 关键词命中，打硬标记 |
| 联系方式、链接、长数字串 | 打硬标记 |
| 整段抄歌词 | 取数时用歌词做 4 字滑窗比对，只记录评论里与歌词重合的**位置**（不保存歌词），重合 ≥40% 打硬标记 |
| 复制粘贴体、近似重复 | 保留点赞高的，其余标"重复于"或"近似" |
| AI 腔的"用户评价总结" | 关键词命中，打软标记"疑似AI腔" |
| "他叫某某"式的私人姓名 | 打软标记"可能提到具体人名"，Agent 要避开 |
| 用空格当逗号的评论 | 截取片段时空格也当作分句点 |

标记只是提示，不是判决：硬标记的评论默认不该选，软标记的由 Agent 判断。

## 尚未验证的点

- 翻到很深的页数（几十页）是否会被限流或要求验证。
- 非热门歌曲、没有热评的歌曲的返回。
- `get_detail` 返回的专辑是否一定带 MID（所以取数时优先用搜索结果里的歌曲对象）。
- 歌词接口对所有歌曲是否都可用；取不到时只是不做抄歌词比对，会在输出里提示。
- 库的接口是非官方的，腾讯调整后可能失效；失效时先看库的仓库有没有更新，再按上面的规则升级固定版本。

## 隐私与合规

- 评论的著作权属于评论者。卡片上只有评论文字、歌名、歌手和来源，不显示评论者的任何信息。
- 歌词受版权保护：只在内存里用来比对，不保存、不显示。
- 封面是专辑版权方的作品。公开发布成品、尤其是商用前，请自行确认平台条款和版权。
