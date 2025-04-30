import os
import discord
from discord import app_commands
from dotenv import load_dotenv
from datetime import datetime, time, timezone, timedelta
import asyncio
import json
import re  # 正規表現モジュールを追加

# 'requests'モジュールを使用していないので削除します

load_dotenv()
TOKEN = os.environ['DISCORD_TOKEN']
DATA_FILE = "/data/akeome_data.json" #VScodeのときはdata/akeome_data.jsonに変更
# NorthFlankのときは/data/akeome_data.jsonに変更
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.reactions = True  # リアクション intents を有効化
client = discord.Client(intents=intents)
client.presence_task_started = False
start_date = None  # 初回のあけおめ日

tree = app_commands.CommandTree(client)

first_new_year_message_sent_today = False
NEW_YEAR_WORD = "あけおめ"

akeome_records = {}
first_akeome_winners = {}
akeome_history = {}
last_akeome_channel_id = None

# ---------- データ永続化 ----------
def save_data():
    data = {
        "first_akeome_winners": first_akeome_winners,
        "akeome_history": {
            date: {uid: ts.isoformat() for uid, ts in recs.items()}
            for date, recs in akeome_history.items()
        },
        "last_akeome_channel_id": last_akeome_channel_id
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_data():
    global first_akeome_winners, akeome_history, last_akeome_channel_id, start_date
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "first_akeome_winners": {},
                "akeome_history": {},
                "last_akeome_channel_id": None
            }, f)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        first_akeome_winners = data.get("first_akeome_winners", {})
        raw_history = data.get("akeome_history", {})
        for date, records in raw_history.items():
            akeome_history[date] = {
                int(uid): datetime.fromisoformat(ts)
                for uid, ts in records.items()
            }
        last_akeome_channel_id = data.get("last_akeome_channel_id")

    if first_akeome_winners:
        earliest_date_str = min(first_akeome_winners.keys())
        start_date = datetime.fromisoformat(earliest_date_str)

async def unarchive_thread(thread: discord.Thread):
    """スレッドがアーカイブされていた場合に解除する"""
    if thread.archived:
        try:
            await thread.edit(archived=False)
            print(f"スレッド '{thread.name}' のアーカイブを解除しました。")
        except discord.errors.NotFound:
            print(f"スレッド '{thread.name}' は見つかりませんでした。")
        except discord.errors.Forbidden:
            print(f"スレッド '{thread.name}' のアーカイブを解除する権限がありません。")
        except Exception as e:
            print(f"スレッド '{thread.name}' のアーカイブ解除中にエラーが発生しました: {e}")

@client.event
async def on_thread_update(before, after):
    """スレッドの状態が更新された際に実行される"""
    if before.archived and not after.archived:
        # アーカイブ解除されたスレッドはここでは処理しない (無限ループ防止)
        return

    if not before.archived and after.archived and after.me:
        # Bot自身が作成したスレッドがアーカイブされた場合、即座にアーカイブ解除を試みる
        await unarchive_thread(after)
    elif not before.archived and after.archived and after.guild.me.guild_permissions.manage_threads:
        # Botにスレッド管理権限がある場合、アーカイブされたスレッドを解除する
        await unarchive_thread(after)

@client.event
async def on_ready():
    global first_new_year_message_sent_today
    print("Bot は準備完了です！")
    await tree.sync()
    load_data()

    now = datetime.now(timezone(timedelta(hours=9)))
    date_str = now.date().isoformat()
    first_new_year_message_sent_today = date_str in first_akeome_winners

    if not client.presence_task_started:
        client.loop.create_task(update_presence())
        client.loop.create_task(reset_daily_flag())
        client.loop.create_task(reset_every_year())
        client.presence_task_started = True

async def update_presence():
    while True:
        try:
            ping = round(client.latency * 1000)
            await client.change_presence(activity=discord.Game(name=f"Ping: {ping}ms"))
            await asyncio.sleep(5)
            await client.change_presence(activity=discord.Game(name=f"サーバー数: {len(client.guilds)}"))
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[update_presence エラー] {e}")
            await asyncio.sleep(10)

async def reset_daily_flag():
    global first_new_year_message_sent_today, akeome_records
    while True:
        now_jst = datetime.now(timezone(timedelta(hours=9)))
        tomorrow = now_jst.date() + timedelta(days=1)
        midnight_tomorrow = datetime.combine(tomorrow, time(0, 0, 0), tzinfo=timezone(timedelta(hours=9)))
        seconds_until_midnight = (midnight_tomorrow - now_jst).total_seconds()
        await asyncio.sleep(seconds_until_midnight)
        first_new_year_message_sent_today = False
        akeome_records.clear()
        print("毎日のフラグと記録をリセットしました。")

async def reset_every_year():
    global start_date
    if not start_date:
        return

    now = datetime.now(timezone(timedelta(hours=9)))
    # next_reset もタイムゾーンを付与するように修正
    next_reset = start_date.replace(year=start_date.year + 1, tzinfo=timezone(timedelta(hours=9)))
    wait_seconds = (next_reset - now).total_seconds()
    print(f"[定期リセット] {next_reset.isoformat()} に実行予定")

    await asyncio.sleep(wait_seconds)

    if last_akeome_channel_id:
        channel = client.get_channel(last_akeome_channel_id)
        if channel:
            sorted_counts = sorted(
                {uid: list(first_akeome_winners.values()).count(uid) for uid in set(first_akeome_winners.values())}.items(),
                key=lambda x: x[1], reverse=True
            )

            def get_name(uid):
                member = channel.guild.get_member(uid)
                return member.display_name if member else f"(ID: {uid})"

            lines = [
                f"{i+1}. {get_name(uid)} 🏆 {count} 回"
                for i, (uid, count) in enumerate(sorted_counts[:10])
            ]

            end_date = next_reset - timedelta(days=1)
            footer_text = f"{start_date.strftime('%Y年%m月%d日')}から{end_date.strftime('%Y年%m月%d日')}まで"
            embed = discord.Embed(title="🏅 一番乗り回数ランキング（リセット前）", description="\n".join(lines), color=0xc0c0c0)
            embed.set_footer(text=footer_text)
            await channel.send(embed=embed)

    first_akeome_winners.clear()
    save_data()
    print("[定期リセット] 一番乗り記録をリセットしました。")

@client.event
async def on_message(message):
    # 投票メッセージの検知とスレッド作成（通常メッセージ形式）
    if isinstance(message.channel, discord.TextChannel) and message.type == discord.MessageType.default:
        # メッセージに「投票」や「選択肢」などが含まれているか確認
        if "投票" in message.content or "選択肢" in message.content:
            thread_name = message.content[:100].strip()

            # 全角スペース（例：「タイトル　詳細」形式）で切り分け
            fullwidth_space_match = re.search(r'　', thread_name)
            if fullwidth_space_match:
                thread_name = thread_name[:fullwidth_space_match.start()].strip()

            try:
                thread = await message.create_thread(name=thread_name, auto_archive_duration=10080)
                print(f"投票メッセージからスレッドを作成しました。スレッド名: '{thread.name}'")
                await message.add_reaction("✅")  # スレッド作成元のメッセージに✅を付与
            except discord.errors.Forbidden as e:
                print(f"投票メッセージからのスレッド作成中に権限エラーが発生しました: {e}")
            except discord.errors.HTTPException as e:
                print(f"投票メッセージからのスレッド作成中に HTTP エラーが発生しました: {e}")
            except Exception as e:
                print(f"投票メッセージからのスレッド作成中に予期せぬエラーが発生しました: {e}")

@client.event
async def on_message(message):
    global first_new_year_message_sent_today, last_akeome_channel_id

    if message.author == client.user:
        return

    now_jst = datetime.now(timezone(timedelta(hours=9)))
    date_str = now_jst.date().isoformat()

    # スレッド自動作成機能 (通常メッセージ)
    if isinstance(message.channel, discord.TextChannel) and message.type == discord.MessageType.default and message.content:
        thread_name = message.content[:100].strip()
        fullwidth_space_match = re.search(r'　', thread_name)
        if fullwidth_space_match:
            thread_name = thread_name[:fullwidth_space_match.start()].strip()

        try:
            thread = await message.create_thread(name=thread_name, auto_archive_duration=10080)
            print(f"メッセージからスレッドを作成しました。スレッド名: '{thread.name}'")
            await message.add_reaction("✅")  # スレッド作成元のメッセージに✅を付与
        except discord.errors.Forbidden as e:
            print(f"メッセージからのスレッド作成中に権限エラーが発生しました: {e}")
        except discord.errors.HTTPException as e:
            print(f"メッセージからのスレッド作成中に HTTP エラーが発生しました: {e}")
        except Exception as e:
            print(f"メッセージからのスレッド作成中に予期せぬエラーが発生しました: {e}")

    # 「あけおめ」機能
    if isinstance(message.channel, discord.TextChannel) and message.type == discord.MessageType.default:
        if message.content.strip() == NEW_YEAR_WORD:
            last_akeome_channel_id = message.channel.id

            if message.author.id not in akeome_records:
                akeome_records[message.author.id] = now_jst
                if date_str not in akeome_history:
                    akeome_history[date_str] = {}
                akeome_history[date_str][message.author.id] = now_jst
                save_data()

            if not first_new_year_message_sent_today:
                await message.channel.send(f"{message.author.mention} が一番乗り！あけましておめでとう！")
                first_new_year_message_sent_today = True
                first_akeome_winners[date_str] = message.author.id
                save_data()

    # 投票メッセージの検知とスレッド作成
    if message.type == discord.MessageType.default and message.embeds:
        await on_message(message)

@client.event
async def on_raw_reaction_add(payload):
    """リアクションが付与された際の処理"""
    if payload.member.bot:
        return
    if payload.emoji.name == "✅":
        channel = client.get_channel(payload.channel_id)
        if isinstance(channel, discord.TextChannel):
            message = await channel.fetch_message(payload.message_id)
            if message.type == discord.MessageType.default:
                await on_message(message)

@tree.command(name="akeome_top", description="今日のあけおめトップ10と自分の順位を表示します")
@app_commands.describe(another="他の集計結果も表示できます")
@app_commands.choices(another=[
    app_commands.Choice(name="過去の一番乗り回数ランキング", value="past"),
    app_commands.Choice(name="今日のワースト10", value="worst")
])
async def akeome_top(interaction: discord.Interaction, another: app_commands.Choice[str] = None):
    now = datetime.now(timezone(timedelta(hours=9)))
    date_str = now.date().isoformat()

    def get_display_name(user_id):
        member = interaction.guild.get_member(user_id)
        return member.display_name if member else f"(ID: {user_id})"

    def get_avatar_icon(user_id):
        member = interaction.guild.get_member(user_id)
        return member.display_avatar.url if member else None

    def user_line(rank, user_id, symbol, extra):
        icon = get_avatar_icon(user_id)
        name = get_display_name(user_id)
        return f"{rank}. [{name}]({icon}) {symbol} {extra}" if icon else f"{rank}. {name} {symbol} {extra}"

    if another is None:
        if not akeome_records:
            await interaction.response.send_message("今日はまだ誰も『あけおめ』していません！", ephemeral=True)
            return

        sorted_records = sorted(akeome_records.items(), key=lambda x: x[1])
        user_rankings = [user_id for user_id, _ in sorted_records]

        lines = []
        for i, user_id in enumerate(user_rankings[:10]):
            time_str = sorted_records[i][1].strftime('%H:%M:%S')
            lines.append(user_line(i+1, user_id, "🕒", time_str))

        if interaction.user.id not in user_rankings[:10]:
            user_index = user_rankings.index(interaction.user.id)
            timestamp = akeome_records[interaction.user.id].strftime('%H:%M:%S')
            lines.append("")
            lines.append(f"あなたの順位\n{user_line(user_index+1, interaction.user.id, '🕒', timestamp)}")

        embed = discord.Embed(title="📜 今日のあけおめランキング", description="\n".join(lines), color=0xc0c0c0)
        embed.set_footer(text=now.strftime("━━━%Y年%m月%d日"))
        await interaction.response.send_message(embed=embed)

    elif another.value == "past":
        if not first_akeome_winners:
            await interaction.response.send_message("まだ一番乗りの記録がありません。", ephemeral=True)
            return

        counts = {}
        for uid in first_akeome_winners.values():
            counts[uid] = counts.get(uid, 0) + 1

        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        lines = []
        for i, (user_id, count) in enumerate(sorted_counts[:10]):
            lines.append(user_line(i+1, user_id, "🏆", f"{count} 回"))

        if start_date:
            end_date = start_date.replace(year=start_date.year + 1) - timedelta(days=1)
            footer_text = f"{start_date.strftime('%Y年%m月%d日')}から{end_date.strftime('%Y年%m月%d日')}まで"
        else:
            footer_text = now.strftime("━━━%Y年%m月%d日")

        embed = discord.Embed(title="🏅 一番乗り回数ランキング", description="\n".join(lines), color=0xc0c0c0)
        embed.set_footer(text=footer_text)
        await interaction.response.send_message(embed=embed)

    elif another.value == "worst":
        if date_str not in akeome_history or not akeome_history[date_str]:
            await interaction.response.send_message("今日のあけおめ記録がありません。", ephemeral=True)
            return

        sorted_worst = sorted(akeome_history[date_str].items(), key=lambda x: x[1], reverse=True)
        lines = []
        for i, (user_id, timestamp) in enumerate(sorted_worst[:10]):
            lines.append(user_line(i+1, user_id, "🐌", timestamp.strftime('%H:%M:%S')))

        embed = discord.Embed(title="🐢 今日のあけおめワースト10", description="\n".join(lines), color=0xc0c0c0)
        embed.set_footer(text=now.strftime("━━━%Y年%m月%d日"))
        await interaction.response.send_message(embed=embed)

client.run(TOKEN)
