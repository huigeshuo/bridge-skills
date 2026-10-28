# GitHub 建仓与 Pages 部署指南

> 从零把一个本地工具（Skill 脚本、单页 HTML）发布到 GitHub，并配置成可分享的在线网页。
> 本文是按 2026-10 实操 `huigeshuo/bridge-skills` 的全过程整理，包含 3 个卡了半小时以上的坑和对应解法，可直接照抄命令。
> 环境：Windows + Git Bash（WorkBuddy 自带 PortableGit），无独立 IDE 授权环境。

---

## 〇、先明确三件事

| 要素 | 说明 | 本例取值 |
|---|---|---|
| 仓库 | 代码和文档的存放地，Public 即公开可搜 | `huigeshuo/bridge-skills` |
| Pages | 把仓库某个目录当静态站点托管，给一条网址 | `huigeshuo.github.io/bridge-skills/` |
| 认证 | 本机往 GitHub 写的凭证，**只走 SSH** | ed25519 密钥 |

一句话原则：**GitHub 负责存，Pages 负责展示，SSH 负责让本机能写进去。**

---

## 一、网页端建仓库

### 1.1 操作

打开 `https://github.com/new`，按下表填写：

| 位置 | 填什么 |
|---|---|
| Owner | 自己账号，不选组织 |
| Repository name | 全小写、短横线分词，如 `bridge-skills` |
| Description | 一句话说清做什么，可留空后补 |
| Visibility | Public（当作品集）/ Private（含未公开资料） |
| Add a README file | **Off** |
| Add .gitignore | **None** |
| Add a license | **No license** |

### 1.2 三个开关为什么必须全关

勾选任意一项，GitHub 会立刻用网页端替你生成一个**初始提交**。等本地再推上去，两边历史没有共同祖先，git 直接报：

```
! [rejected]        main -> main (fetch first)
```

或

```
fatal: refusing to merge unrelated histories
```

这时只能 `git pull --allow-unrelated-histories` 硬合，或 `git push -f` 强推，都会多一步麻烦。**本地已经有内容时，永远让 GitHub 建一个纯空仓库。**

README、`.gitignore`、`LICENSE` 三样本地自己写，内容更准确，还能随代码一起进版本管理。

### 1.3 建完的标志

页面跳到 `Quick setup — if you've done this kind of thing before`，给出一串 `git remote add origin ...` 命令。看到这页就对了，**那一屏命令不用执行**，因为我们本地已有提交。

---

## 二、把本机 Skill 打包成仓库

自研 Skill 的标准结构是 `SKILL.md` + `scripts/` + `references/`，整目录可直接当仓库子目录。

### 2.1 组装骨架

```bash
SRC="$HOME/.workbuddy/skills"          # 本机 skills 目录
REPO="/f/SZH 文件夹/WorkBuddy/bridge-skills"   # 目标仓库，放持久目录，别放会话临时目录
mkdir -p "$REPO"
cd "$REPO"
mkdir -p bridge-sketch tied-arch-sketch box-girder-index/data box-girder-index/scripts
cp -r "$SRC/bridge-sketch/." ./bridge-sketch/
cp -r "$SRC/tied-arch-sketch/." ./tied-arch-sketch/
cp "$SRC/box-girder-index/SKILL.md" ./box-girder-index/
cp -r "$SRC/box-girder-index/scripts/." ./box-girder-index/scripts/
```

> 仓库目录**不要放在 Obsidian 库里**。`.git` 目录会被 Obsidian 反复索引，几千个对象文件会让打开库明显变慢。

### 2.2 逐份检查脚本依赖

```bash
grep -hE "^(import|from) [a-zA-Z_]" */scripts/*.py | sort -u
```

只允许标准库 + 少量常见第三方（如 `openpyxl`）。有重依赖就在 README 里写清安装命令，别让人 clone 完跑不起来。

### 2.3 先跑一遍，README 里的命令必须实测过

```bash
mkdir -p out
python bridge-sketch/scripts/generate_bridge_sketch.py --main-span 280 --side-span-left 130 --side-span-right 90 -o out/t1.svg
python tied-arch-sketch/scripts/generate_tied_arch_sketch.py --arch-span 320 --rise 56.44 --axis parabola -o out/t2.svg
ls -l out/
```

跑不通的命令写进 README 等于挖坑。**示例参数一定要从脚本的 `add_argument` 里核对**，不能凭印象写。

---

## 三、敏感数据防护（公开前必做）

这是整件事里最容易出事故的环节。工程类工具的数据文件往往带真实项目名和精确工程量。

### 3.1 `.gitignore` 白名单策略

原则：**默认全拦，只放行示例**。

```gitignore
# 真实指标数据
data/*.json
!data/example_indicators.json

# 设计院原始汇总表
*.xlsx
*.xls

# 构建产物与临时文件
out/
__pycache__/
*.pyc
.venv/
node_modules/
.DS_Store
Thumbs.db
```

### 3.2 验证规则真的生效

```bash
git check-ignore -v box-girder-index/data/box_girder_indicators.json
```

有输出（打印命中哪条规则）才算拦住。**没有输出就是没拦住，必须回去改。**

### 3.3 上线前用真实值逐项搜一遍

```bash
python - <<'EOF'
import json, io
lib = json.load(io.open('真实数据.json', encoding='utf-8'))
html = io.open('docs/index.html', encoding='utf-8').read()
vals = set()
for r in lib:
    for k in ('project', 'block', 'bridge_src', 'source_file', 'name'):
        v = r.get(k)
        if isinstance(v, str) and v.strip() and v != '—':
            vals.add(v.strip())
hit = sorted(v for v in vals if v in html)
print('候选敏感值 %d 个，命中 %d 个' % (len(vals), len(hit)))
for h in hit[:15]:
    print('   >>>', h)
EOF
```

**判读命中结果**：如果命中的是 `A`、`C`、`H-2` 这种单字母或极短代号，属于「字母串恰好出现在 HTML 标签/样式里」的误报，看上下文即可排除；命中 `陆口大桥`、`WD高速` 这种完整实名，就是真泄露，必须处理。

### 3.4 脱敏到哪一级

| 级别 | 做法 | 适用 |
|---|---|---|
| 代号化 | 桥名换成 `LKDQ` `FHDD` 拼音首字母，保留明细 | 同行看构造尺寸规律 |
| 统计摘要 | 只给分区间统计，不给逐条明细 | 最稳妥，本文选的这级 |

页面里显式写一句「本页为统计摘要，不含工程名、桥名等可溯源信息」，比藏在角落更有说服力。

---

## 四、本地初始化与首次提交

### 4.1 初始化并写齐全套文件

```bash
cd "/f/SZH 文件夹/WorkBuddy/bridge-skills"
git init -b main
```

必备四个文件：

| 文件 | 作用 |
|---|---|
| `README.md` | 首页说明：包含什么、怎么跑、数据在哪 |
| `.gitignore` | 敏感数据白名单 |
| `.gitattributes` | 换行统一，避免 Windows 提交后整个文件变成改动 |
| `LICENSE` | 声明授权；MIT 即「随便用，出事别找我」 |

`.gitattributes` 内容：

```gitattributes
* text=auto eol=lf
*.png binary
*.jpg binary
*.xlsx binary
```

### 4.2 配置提交身份（决定是否泄露邮箱）

**这一步务必在首次 commit 之前做。** commit 的作者邮箱是明文写死在提交对象里的，推上去就永久公开。

先查自己的用户 ID：

```bash
curl -s "https://api.github.com/users/huigeshuo" | grep -o '"id": *[0-9]*'
# "id": 305686175
```

用带 ID 的 noreply 地址（GitHub 官方推荐格式）：

```bash
git config --global user.name "huigeshuo"
git config --global user.email "305686175+huigeshuo@users.noreply.github.com"
```

**为什么不直接用 `huigeshuo@users.noreply.github.com`**：不带数字 ID 的旧格式 GitHub 不认，贡献图不点亮，commit 页显示灰色默认头像。带了 ID 才既隐私又正常计贡献。

再开网页端两个开关（`https://github.com/settings/emails`）：

- **Keep my email addresses private** → 网页上在线编辑文件也不会带出真实邮箱
- **Block command line pushes that expose my email** → 别的机器误用真实邮箱提交时，git 直接拒绝推送，而不是默默泄露

### 4.3 提交并核对

```bash
git add -A
git status --short              # 看清单，确认没有真实数据文件
git commit -m "初始提交：工具集"
git log --format="%h  %an <%ae>  %s"
```

`%ae` 输出的必须是那个带 ID 的 noreply 地址。

---

## 五、认证：HTTPS 走不通，直接用 SSH

### 5.1 三种方式实测结果

| 方式 | 结果 | 原因 |
|---|---|---|
| HTTPS + 浏览器弹窗授权 | ✗ 卡死 180 秒无响应 | 后台会话里弹不出窗口，`git push` 就一直等 |
| `git-credential-manager github login --device` | ✗ 30 秒无输出 | 设备码流程同样依赖交互式终端 |
| **SSH 密钥** | ✓ 一次通过 | 无交互，纯密钥握手 |

**结论：这类无图形界面的自动化环境，一律走 SSH，不要浪费时间试弹窗。**

### 5.2 生成密钥并贴到 GitHub

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -C "huigeshuo bridge-skills" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

复制输出的整行（`ssh-ed25519` 开头到结尾，中途不能断行），打开：

**`https://github.com/settings/ssh/new`**

- Title：随便起，给自己认，如 `家用台式机`
- Key type：保持 `Authentication Key`
- Key：粘贴整行
- 点 **Add SSH key**

> 公钥不是密码，贴到哪里都不怕泄露；**私钥 `id_ed25519`（无 .pub 后缀）永远不发出去**。

### 5.3 验证握手

```bash
ssh-keygen -lf ~/.ssh/id_ed25519.pub     # 记下指纹，和网页上显示的对上
ssh -T -o StrictHostKeyChecking=accept-new git@github.com
```

成功标志：

```
Hi huigeshuo! You've successfully authenticated, but GitHub does not provide shell access.
```

这句出现就说明贴上去的正是本机这把钥匙。

### 5.4 换 remote 并推送

```bash
git config core.quotepath false         # 中文文件名不显示成 \344\270\255
git remote add origin git@github.com:huigeshuo/bridge-skills.git
# 若已存在 HTTPS 地址：git remote set-url origin git@github.com:huigeshuo/bridge-skills.git
git push -u origin main
```

### 5.5 公司网络只开 443 时的备选

```bash
timeout 6 bash -c 'cat < /dev/null > /dev/tcp/github.com/22' && echo "22 通" || echo "22 不通"
timeout 6 bash -c 'cat < /dev/null > /dev/tcp/ssh.github.com/443' && echo "443 通"
```

22 不通就改 `~/.ssh/config`：

```
Host github.com
  HostName ssh.github.com
  Port 443
  User git
```

---

## 六、修改已推提交的作者信息

如果已经推上去了才发现邮箱不对，**仓库刚建、无他人协作时**可以安全改写历史。

```bash
cd "/f/SZH 文件夹/WorkBuddy/bridge-skills"
git config user.email "305686175+huigeshuo@users.noreply.github.com"

FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f --env-filter '
export GIT_AUTHOR_EMAIL="305686175+huigeshuo@users.noreply.github.com"
export GIT_COMMITTER_EMAIL="305686175+huigeshuo@users.noreply.github.com"
export GIT_AUTHOR_NAME="huigeshuo"
export GIT_COMMITTER_NAME="huigeshuo"
' -- --all

git push -f origin main
```

### 一个必须知道的事实

改写历史**不等于删除**。实测旧提交 SHA 仍然可通过 API 访问：

```
旧提交 63596ce: HTTP 200
旧提交 bd9e519: HTTP 200
```

它们已经不在 `main` 分支上，但 GitHub 保留着对象，知道 SHA 就能打开。爬虫和第三方代码搜索站也可能早已抓取。

**所以：真实邮箱一旦推上去，就当它已公开。唯一的防线是提交前就配好 noreply。**

---

## 七、GitHub Pages 部署

### 7.1 只能网页操作

Pages 的开关没有暴露给 SSH，必须手动点：**`https://github.com/USER/REPO/settings/pages`**

1. **Source** 选 `Deploy from a branch`
2. **Branch** 左边 `main`，右边目录**从 `/(root)` 改成 `/docs`**
3. 点 **Save**

> 第 2 步的目录是最容易漏的。选成 `/(root)` 而文件在 `docs/` 里，结果就是 404，且报错信息不会告诉你原因。

### 7.2 目录与访问路径的对应

```
仓库/
└── docs/
    ├── index.html      → https://USER.github.io/REPO/
    └── box-girder.html → https://USER.github.io/REPO/box-girder.html
```

`index.html` 就是首页，其他 `.html` 按文件名直接访问，不需要额外配置路由。

**文件命名建议用英文短横线**：中文文件名在 URL 里会变成一长串百分号编码，发出去很难看，也容易在聊天软件里被截断。

### 7.3 构建期 404 是正常的

保存后页面顶部出现：

```
Your site is live at https://USER.github.io/REPO/
```

但它此刻还没真就绪。首次部署要跑一次构建，**1~2 分钟**；之后每次推送新增文件，也会有同样的延迟。

轮询等待：

```bash
for i in 1 2 3 4 5; do
  code=$(curl -s -o /tmp/p.html -w "%{http_code}" --max-time 45 "https://USER.github.io/REPO/page.html")
  echo "第 $i 次: HTTP $code"
  [ "$code" = "200" ] && break
  sleep 25
done
grep -o "<title>[^<]*</title>" /tmp/p.html
```

### 7.4 上线后核对三件事

```bash
# 1. 状态与源分支
curl -s "https://api.github.com/repos/USER/REPO/pages" \
  | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('status'), d.get('source'))"

# 2. 文件确实在远端
curl -s "https://api.github.com/repos/USER/REPO/contents/docs" | grep -o '"name": *"[^"]*"'

# 3. 页面真的能打开且标题正确
curl -s -o /dev/null -w "%{http_code}  %{size_download}字节\n" "https://USER.github.io/REPO/"
```

---

## 八、国内访问速度的现实

`github.io` 的 IP（`185.199.108.153`）在国内被限速。本机 curl 实测：

| 阶段 | 耗时 |
|---|---|
| DNS 解析 | 0.0001 s（缓存） |
| TCP 连接 | 0.0006 s |
| TLS 握手 | 3.8 ~ 4.8 s |
| 首字节 | 5.8 s |
| 总计 | 33 ~ 36 s |

65 KB 传 30 秒 ≈ 2 KB/s。

**但 curl 的数字不代表浏览器体验。** 浏览器有 HTTP/2 多路复用、TLS session 复用、磁盘缓存，实测「能打开，可以接受」。判断标准应该是**手机 + 移动流量**实测，那才接近甲方和同事的真实场景。

确实需要国内提速时的备选：

| 方案 | 国内速度 | 门槛 |
|---|---|---|
| 腾讯云 EdgeOne Pages | 快，有国内节点 | 注册腾讯云，免费额度够用，免费子域名免备案 |
| Cloudflare Pages | 中等，时快时慢 | 注册即可，`*.pages.dev` 免费 |
| Gitee Pages | 快 | 需实名，免费版已收紧 |

另有一条兜底：**单文件 HTML 直接微信发过去，双击就开**，零延迟、不依赖网络。在线链接的价值只在于「对方随手一点就能看」。

---

## 九、日常更新流程

```bash
cd "/f/SZH 文件夹/WorkBuddy/bridge-skills"
git add -A
git commit -m "更新说明"
git push
```

推送后 Pages 约 1 分钟自动重建，**不需要再进设置页面**。

### 一个必须守住的纪律

如果 `docs/index.html` 是由 `build.py` 之类的脚本从数据生成的，**不要直接编辑 `docs/index.html`**——下次重新生成会覆盖掉。正确链路是：

```bash
cd continuous-girder-lookup
cp /path/to/新的data.json .
python build.py
cp index.html ../docs/index.html
cd .. && git add -A && git commit -m "更新数据" && git push
```

---

## 十、排错速查

| 现象 | 原因 | 解决 |
|---|---|---|
| `Please tell me who you are` | 没配 `user.name` / `user.email` | `git config --global user.email "...noreply..."` |
| `git push` 卡住几分钟无输出 | 弹窗认证在无图形环境起不来 | 改 SSH，别重试 HTTPS |
| `! [rejected] (fetch first)` | 远端有网页端生成的初始提交 | 建库时三个开关全关；已发生则 `git pull --allow-unrelated-histories` |
| Pages 打开 404 | 目录选成 `/(root)`，或构建未完 | 回设置改 `/docs`；等 1~2 分钟再刷 |
| Pages 页面样式怪、显示文件列表 | 该目录没有 `index.html` | 确认首页文件名就是 `index.html` |
| Topics 报「超过 50 字符」 | 整串粘贴，被当成一个 topic | 输入一个 → 回车 → 再输下一个 |
| Topics 中文被拒 | 只允许小写字母、数字、连字符 | 用英文标签 |
| 推送被拒、提示邮箱将泄露 | 开了 Block 开关但用了真实邮箱 | 改 `user.email` 为 noreply 再推 |
| 中文文件名显示成 `\344\270\255` | git 默认转义 | `git config core.quotepath false` |
| `git commit` 报「无需提交」但远端没更新 | 只是 commit 成功但 push 没走完 | 单独执行 `git push origin main`，看退出码 |

---

## 十一、一次性命令清单

从零到上线的完整命令，替换 `USER` / `REPO` 即可复用：

```bash
# 1. 身份（只配一次，全局生效）
curl -s "https://api.github.com/users/USER" | grep -o '"id": *[0-9]*'
git config --global user.name "USER"
git config --global user.email "ID+USER@users.noreply.github.com"

# 2. 本地初始化
cd /path/to/REPO
git init -b main
git config core.quotepath false
git add -A && git status --short
git commit -m "初始提交"

# 3. SSH 密钥（只配一次）
ssh-keygen -t ed25519 -C "USER $REPO" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub        # 贴到 https://github.com/settings/ssh/new
ssh -T git@github.com            # 应回 Hi USER!

# 4. 接远程并推送
git remote add origin git@github.com:USER/REPO.git
git push -u origin main

# 5. 网页端启 Pages：Settings → Pages → main + /docs → Save
# 6. 等 1~2 分钟后验证
curl -s -o /dev/null -w "%{http_code}\n" "https://USER.github.io/REPO/"
```

---

## 十二、本次实操记录

| 项目 | 结果 |
|---|---|
| 仓库 | `https://github.com/huigeshuo/bridge-skills` |
| 在线工具 1 | `https://huigeshuo.github.io/bridge-skills/` （连续刚构箱梁构造尺寸速查） |
| 在线工具 2 | `https://huigeshuo.github.io/bridge-skills/box-girder.html` （箱梁技术指标速查） |
| 内容 | 4 个工具目录 + MIT 许可 + 12 个 Topics |
| 卡点 1 | HTTPS / GCM 设备码认证在无头环境全部失效，耗时约 1 小时，最终 SSH 解决 |
| 卡点 2 | 建库时若勾 README 会产生历史冲突，所幸未勾 |
| 卡点 3 | Pages 首次构建 + 新增文件后均有 404 窗口期，误判为配置错误 |
| 数据安全 | 92 条箱梁指标 + 34 条刚构桥例**全部留在本地**，仓库零真实工程名 |

---

## 附：三条铁律

1. **建库三个开关全关**，本地内容自己带。
2. **首次 commit 前配好 noreply 邮箱**，推上去就撤不回。
3. **公开前用真实值逐个 grep**，工具类仓库的数据泄露只在这一步能拦住。
