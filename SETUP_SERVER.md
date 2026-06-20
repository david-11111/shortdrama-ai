# 服务器部署配置

## 一、服务器准备

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | sh

# 安装 docker compose（如果系统没有的话）
apt install -y docker-compose-plugin

# 把当前用户加入 docker 组（避免每次 sudo）
sudo usermod -aG docker $USER
# 重新登录使组生效
```

## 二、在服务器上 clone 项目

```bash
git clone https://github.com/david-11111/shortdrama-ai.git /path/to/project
cd /path/to/project
cp .env.example .env
# 编辑 .env 填入真实的 API key 和密钥
```

## 三、在 GitHub 仓库配置 Secrets

去 GitHub 仓库页面 → Settings → Secrets and variables → Actions → New repository secret，添加：

| Secret | 值 |
|--------|-----|
| `SERVER_HOST` | 服务器公网 IP |
| `SERVER_USER` | SSH 用户名 |
| `SERVER_PASSWORD` | SSH 密码 |
| `SERVER_PORT` | SSH 端口（默认 22，可省略） |
| `SERVER_PROJECT_PATH` | 服务器上项目的绝对路径 |

## 四、测试部署

推送代码到 main 分支，GitHub Actions 会自动：
1. 跑测试
2. SSH 上服务器
3. git pull + docker compose up -d

观察 Actions 页面确认部署成功。
