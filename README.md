# GitHub Activity Monitor

![Python Version](https://img.shields.io/badge/python-3.7%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

一个监控GitHub用户动态并推送到钉钉/飞书群聊的自动化工具。

## 功能特性

- 🔔 **实时监控**：自动获取GitHub用户动态（Star、Fork、Push等事件）
- 📊 **信息丰富**：显示仓库描述、语言、Star数等详细信息
- 📱 **多平台支持**：同时支持钉钉和飞书机器人通知
- ⏱ **防重复推送**：基于事件ID的去重机制

## 支持的事件类型

| 事件类型 | 图标 | 描述 |
|---------|------|------|
| WatchEvent | ⭐ | Star仓库 |
| ForkEvent | 🍴 | Fork仓库 |
| PushEvent | ⬆️ | 推送代码 |
| PullRequestEvent | 🔀 | 提交PR |
| IssuesEvent | ❗ | 创建Issue |
| CreateEvent | 🆕 | 创建仓库/分支等 |
| ReleaseEvent | 🚀 | 发布新版本 |

## 快速开始

### 安装依赖

```bash
pip install pyyaml requests sqlite3
```

### 配置文件
```yaml
github:
  username: "你的GitHub用户名"
  token: "你的GitHub Token"
  max_events: 10
  poll_interval: 60  # 检查间隔(秒)

logging:
  level: "INFO"
  file: "github_monitor.log"

database:
  path: "github_events.db"

notifications:
  dingtalk:
    enable: true
    webhook: "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"
    secret: "SECRET"  # 可选
  feishu:
    enable: true
    webhook: "https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_TOKEN"
    secret: "SECRET"  # 可选
```

### GitHub Token 配置

访问 [GitHub Token设置页面](https://github.com/settings/tokens)GitHub Token设置页面

生成一个有public_repo权限的新Token


## 运行监控
```python
python3 github_monitor.py
```

