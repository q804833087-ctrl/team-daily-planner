# 团队日计划

7 人小组日计划系统：早上填计划、中午/晚上确认完成，管理者看板汇总。

## 访问地址

### 方式 A：立即使用（临时公网链接）

双击 **`启动公网访问.bat`**，等待出现 `https://xxxx.trycloudflare.com` 链接，发到微信群即可。

- 手机/微信可直接打开
- 管理者入口在首页底部，PIN 默认 `8888`
- ⚠️ 需保持电脑开机；关闭后链接失效；每次重启链接会变

### 方式 B：永久免费域名（推荐）

部署到 **Render（免费域名）+ Neon（免费数据库）**，获得固定地址如：

```
https://team-daily-planner.onrender.com
```

**一键部署步骤：**

1. 双击运行 **`deploy.ps1`**（或在 PowerShell 中 `.\deploy.ps1`）
2. 按提示注册 [Neon](https://neon.tech) → 复制 `DATABASE_URL`
3. 注册 [Render](https://render.com) → 连接 GitHub → 部署 Blueprint
4. 在 Render 环境变量填入 `DATABASE_URL`
5. 获得永久 HTTPS 域名，微信可收藏

| 服务 | 费用 | 作用 |
|------|------|------|
| Render | 免费 | 托管网页，提供 `*.onrender.com` 域名 |
| Neon | 免费永久 | PostgreSQL 数据库，数据不丢失 |
| GitHub | 免费 | 存放代码，Render 自动部署 |

> Render 免费版 15 分钟无人访问会休眠，首次打开需等 ~30 秒唤醒。

## 本地开发

```powershell
cd 团队日计划
pip install -r requirements.txt
python app.py
# 浏览器打开 http://127.0.0.1:5000
```

## 配置（config.json）

```json
{
  "team_name": "我的团队",
  "members": ["成员一", "成员二", ...],
  "manager_pin": "8888",
  "schedule": {
    "morning_deadline": "09:00",
    "noon_check": "12:00",
    "evening_check": "18:00"
  }
}
```

修改组员姓名后，若已部署到 Render，需 `git push` 触发重新部署。

## 使用流程

| 时段 | 组员操作 |
|------|----------|
| 09:00 前 | 选姓名 → 添加今日任务 → 提交 |
| 12:00 左右 | 勾选已完成 → 提交午间确认 |
| 18:00 左右 | 勾选已完成 → 提交晚间确认 |
| 随时 | 管理者 PIN 登录 → 看板 / 历史趋势 |

## 文件说明

| 文件 | 说明 |
|------|------|
| `app.py` | 主程序 |
| `db.py` | 数据库（本地 SQLite / 云端 PostgreSQL） |
| `启动公网访问.bat` | 临时公网链接（今天就能用） |
| `deploy.ps1` | 永久云部署助手 |
| `render.yaml` | Render 一键部署配置 |
