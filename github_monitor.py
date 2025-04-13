import yaml
import requests
import sqlite3
import logging
import time
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime, timedelta
import re

# 加载配置
with open("config.yaml") as f:
    config = yaml.safe_load(f)


# 日志配置
def setup_logger():
    logger = logging.getLogger("GitHubMonitor")
    logger.setLevel(config["logging"]["level"])

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # 文件输出
    file_handler = logging.FileHandler(config["logging"]["file"])
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


logger = setup_logger()


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(config["database"]["path"])
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pushed_events (
                event_id TEXT PRIMARY KEY,
                pushed_at TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS repo_cache (
                name TEXT PRIMARY KEY,
                description TEXT,
                language TEXT,
                stars INTEGER,
                last_updated TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_cache (
                login TEXT PRIMARY KEY,
                avatar_url TEXT,
                last_updated TIMESTAMP
            )
        """)
        self.conn.commit()

    def is_pushed(self, event_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM pushed_events WHERE event_id=?", (event_id,))
        return cursor.fetchone() is not None

    def mark_pushed(self, event_id):
        try:
            self.conn.execute(
                "INSERT INTO pushed_events VALUES (?, ?)",
                (event_id, datetime.now().isoformat())
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def get_repo_info(self, repo_name):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT description, language, stars FROM repo_cache WHERE name=?",
            (repo_name,)
        )
        return cursor.fetchone()

    def cache_repo_info(self, repo_name, info):
        self.conn.execute(
            """INSERT OR REPLACE INTO repo_cache 
            VALUES (?, ?, ?, ?, ?)""",
            (repo_name, info.get("description"),
             info.get("language"), info.get("stargazers_count", 0),
             datetime.now().isoformat())
        )
        self.conn.commit()

    def get_user_avatar(self, login):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT avatar_url FROM user_cache WHERE login=?",
            (login,)
        )
        result = cursor.fetchone()
        return result[0] if result else None

    def cache_user_avatar(self, login, avatar_url):
        self.conn.execute(
            """INSERT OR REPLACE INTO user_cache 
            VALUES (?, ?, ?)""",
            (login, avatar_url, datetime.now().isoformat())
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


class Notifier:
    def __init__(self):
        self.db = Database()

    def _get_repo_details(self, repo_name):
        cached = self.db.get_repo_info(repo_name)
        if cached:
            return {
                "description": cached[0],
                "language": cached[1],
                "stargazers_count": cached[2]
            }

        try:
            response = requests.get(
                f"https://api.github.com/repos/{repo_name}",
                headers={"Authorization": f"token {config['github']['token']}"},
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                self.db.cache_repo_info(repo_name, data)
                return {
                    "description": data.get("description"),
                    "language": data.get("language"),
                    "stargazers_count": data.get("stargazers_count", 0)
                }
        except Exception as e:
            logger.warning(f"获取仓库详情失败: {e}")

        return {
            "description": "暂无描述",
            "language": "",
            "stargazers_count": 0
        }

    def _get_user_avatar(self, login):
        cached = self.db.get_user_avatar(login)
        if cached:
            return cached

        try:
            response = requests.get(
                f"https://api.github.com/users/{login}",
                headers={"Authorization": f"token {config['github']['token']}"},
                timeout=3
            )
            if response.status_code == 200:
                avatar_url = response.json().get("avatar_url", "")
                self.db.cache_user_avatar(login, avatar_url)
                return avatar_url
        except Exception as e:
            logger.warning(f"获取用户头像失败: {e}")

        return "https://github.com/identicons/app.png"

    def format_message(self, event):
        try:
            event_type = event["type"]
            actor = event["actor"]["login"]
            actor_avatar = self._get_user_avatar(actor) + "?size=20"
            repo_name = event["repo"]["name"]
            repo_url = f"https://github.com/{repo_name}"
            time_str = datetime.strptime(
                event["created_at"], "%Y-%m-%dT%H:%M:%SZ"
            ).strftime("%Y-%m-%d %H:%M")

            # 获取仓库详情
            repo_info = self._get_repo_details(repo_name)
            description = repo_info["description"]
            language = repo_info["language"]
            stars = repo_info["stargazers_count"]

            # 操作类型映射（新增ReleaseEvent）
            actions = {
                "WatchEvent": "⭐ Starred",
                "ForkEvent": "🍴 Forked",
                "PullRequestEvent": "🔀 提交PR到",
                "IssuesEvent": "❗ 创建Issue",
                "PushEvent": "⬆️ 推送代码到",
                "CreateEvent": "🆕 创建",
                "ReleaseEvent": "🚀 发布了新版本"
            }

            # 处理ReleaseEvent的特殊信息
            release_info = ""
            if event_type == "ReleaseEvent":
                release_name = event["payload"]["release"].get("name", "")
                tag_name = event["payload"]["release"].get("tag_name", "")
                release_info = f"\n**版本**: {tag_name} {release_name}"

            return "\n".join([
                "### ✨ GitHub动态通知",
                f"![用户头像]({actor_avatar}) **[{actor}](https://github.com/{actor})**",
                f"**⌚ 时间**: {time_str}",
                f"**🔧 操作**: {actions.get(event_type, event_type)}",
                f"**📦 仓库**: [{repo_name}]({repo_url})",
                f"**📝 描述**: {description}{release_info}",
                f"**🌐 语言**: {language} | **⭐ Stars**: {stars}",
                "---"
            ])

        except Exception as e:
            logger.error(f"格式化消息失败: {e}")
            return "\n".join([
                "### GitHub动态通知",
                "**警告**: 消息格式化出错",
                f"```\n{str(e)}\n```"
            ])

    def send_all(self, message):
        # 发送到所有钉钉机器人
        if config["notifications"]["dingtalk"]["enable"]:
            for bot in config["notifications"]["dingtalk"].get("bots", []):
                self._send_dingtalk(message, bot)

        # 发送到所有飞书机器人
        if config["notifications"]["feishu"]["enable"]:
            for bot in config["notifications"]["feishu"].get("bots", []):
                self._send_feishu(message, bot)

    def _send_dingtalk(self, message, bot_config):
        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "GitHub动态通知",
                    "text": message.replace("\n", "\n\n")
                }
            }
            url = bot_config["webhook"]
            if bot_config.get("secret"):
                timestamp = str(round(time.time() * 1000))
                sign = self._generate_dingtalk_sign(bot_config["secret"], timestamp)
                url += f"&timestamp={timestamp}&sign={sign}"

            response = requests.post(url, json=payload, timeout=5)
            if response.status_code != 200:
                logger.error(f"钉钉发送失败到 {bot_config.get('name', '未知机器人')}: {response.text}")
            else:
                logger.info(f"发现新事件，已发送到钉钉机器人 {bot_config.get('name', '未知机器人')}")
        except Exception as e:
            logger.error(f"钉钉发送失败到 {bot_config.get('name', '未知机器人')}: {e}")

    def _send_feishu(self, message, bot_config):
        try:
            webhook_url = bot_config["webhook"]

            # 准备基础请求数据
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {
                            "content": "✨ GitHub动态通知",
                            "tag": "plain_text"
                        },
                        "template": "blue"
                    },
                    "elements": [{
                        "tag": "div",
                        "text": {
                            "content": self._format_for_feishu(message),
                            "tag": "lark_md"
                        }
                    }]
                }
            }

            # 处理签名逻辑
            if bot_config.get("secret"):
                timestamp = str(int(time.time()))  # 秒级时间戳
                sign = self._generate_feishu_sign(bot_config["secret"], timestamp)

                # 将签名参数添加到URL中
                parsed_url = urllib.parse.urlparse(webhook_url)
                query = urllib.parse.parse_qs(parsed_url.query)
                query.update({
                    "timestamp": [timestamp],
                    "sign": [sign]
                })
                new_query = urllib.parse.urlencode(query, doseq=True)
                webhook_url = urllib.parse.urlunparse(
                    parsed_url._replace(query=new_query)
                )

            # 发送请求
            response = requests.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            if response.status_code != 200:
                error_msg = f"飞书推送失败到 {bot_config.get('name', '未知机器人')}: {response.status_code}"
                try:
                    error_detail = response.json()
                    error_msg += f" | 错误码: {error_detail.get('code')} | 消息: {error_detail.get('msg')}"
                except:
                    error_msg += f" | 响应: {response.text}"
                logger.error(error_msg)
            else:
                logger.info(f"发现1个新事件，飞书推送成功到 {bot_config.get('name', '未知机器人')}")

        except Exception as e:
            logger.error(f"飞书发送异常到 {bot_config.get('name', '未知机器人')}: {str(e)}")

    def _generate_dingtalk_sign(self, secret, timestamp):
        """钉钉签名生成方法"""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        return urllib.parse.quote_plus(base64.b64encode(hmac_code))

    def _generate_feishu_sign(self, secret, timestamp):
        """飞书签名生成方法"""
        string_to_sign = f"{timestamp}\n{secret}".encode('utf-8')
        hmac_code = hmac.new(
            secret.encode('utf-8'),
            string_to_sign,
            digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode('utf-8')

    def _format_for_feishu(self, message):
        """飞书专用格式化"""
        try:
            # 1. 转换图片语法（如果存在）
            if '![' in message and '](' in message:
                message = re.sub(r'!\[.*?\]\(.*?\)', '', message)

            # 2. 简化标题格式
            message = message.replace("### ✨ GitHub动态通知\n", "")

            # 3. 确保双换行
            message = message.replace("\n", "\n\n")

            return message
        except Exception as e:
            logger.error(f"飞书消息格式化异常: {e}")
            return "GitHub动态通知（消息格式化出错）"


def monitor():
    notifier = Notifier()
    logger.info("🚀 GitHub监控启动")

    try:
        while True:
            try:
                # 获取事件
                events = requests.get(
                    f"https://api.github.com/users/{config['github']['username']}/received_events",
                    headers={"Authorization": f"token {config['github']['token']}"},
                    params={"per_page": config["github"]["max_events"]},
                    timeout=10
                ).json()

                # 处理事件
                new_events = 0
                for event in events:
                    if not notifier.db.is_pushed(event["id"]):
                        msg = notifier.format_message(event)
                        notifier.send_all(msg)
                        notifier.db.mark_pushed(event["id"])
                        new_events += 1
                        time.sleep(0.5)

                logger.info(f"本轮检查完成，发现{new_events}个新事件")
                time.sleep(config["github"]["poll_interval"])

            except requests.exceptions.RequestException as e:
                logger.error(f"网络请求异常: {e}")
                time.sleep(60)
            except Exception as e:
                logger.error(f"处理异常: {e}")
                time.sleep(60)

    except KeyboardInterrupt:
        logger.info("🛑 手动停止监控")
    finally:
        notifier.db.close()


if __name__ == "__main__":
    monitor()