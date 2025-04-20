#main.py
import os
import discord
from discord import app_commands
from dotenv import load_dotenv
from datetime import datetime, time, timezone, timedelta
import asyncio
import re
import json

load_dotenv()
TOKEN = os.environ['DISCORD_TOKEN']
DATA_FILE = "akeome_data.json"

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
client = discord.Client(intents=intents)
client.presence_task_started = False
tree = app_commands.CommandTree(client)

first_new_year_message_sent_today = False
NEW_YEAR_WORD = "あけおめ"

akeome_records = {}  # {user_id: timestamp}
first_akeome_winners = {}  # {date_string: user_id}
akeome_history = {}  # {date_string: {user_id: timestamp}}

# ---------- データ永続化 ----------
def save_data():
    data = {
        "first_akeome_winners": first_akeome_winners,
        "akeome_history": {
            date: {uid: ts.isoformat() for uid, ts in recs.items()}
            for date, recs in akeome_history.items()
        }
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_data():
    global first_akeome_winners, akeome_history
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            first_akeome_winners = data.get("first_akeome_winners", {})
            raw_history = data.get("akeome_history", {})
            for date, records in raw_history.items():
                akeome_history[date] = {
                    int(uid): datetime.fromisoformat(ts)
                    for uid, ts in records.items()
                }
    else:
        first_akeome_winners = {}
        akeome_history = {}

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
        client.presence_task_started = True

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

    client.loop.create_task(reset_daily_flag())

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

@client.event
async def on_message(message):
    global first_new_year_message_sent_today

    if message.author == client.user:
        return

    now_jst = datetime.now(timezone(timedelta(hours=9)))
    date_str = now_jst.date().isoformat()

    if isinstance(message.channel, discord.TextChannel) and message.type == discord.MessageType.default:
        if message.content.strip() == NEW_YEAR_WORD:
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

@tree.command(name="akeome_top", description="今日のあけおめトップ10と自分の順位を表示します")
@app_commands.describe(another="他の集計結果も表示できます")
@app_commands.choices(another=[
    app_commands.Choice(name="過去の一番乗り回数ランキング", value="past"),
    app_commands.Choice(name="今日のワースト10", value="worst")
])
async def akeome_top(interaction: discord.Interaction, another: app_commands.Choice[str] = None):
    now = datetime.now(timezone(timedelta(hours=9)))
    date_str = now.date().isoformat()

    def mention_or_id(uid):
        return f"<@!{uid}>"

    if another is None:
        if not akeome_records:
            await interaction.response.send_message("今日はまだ誰も『あけおめ』していません！", ephemeral=True)
            return

        sorted_records = sorted(akeome_records.items(), key=lambda x: x[1])
        user_rankings = [user_id for user_id, _ in sorted_records]

        embed = discord.Embed(title="📜 今日のあけおめランキング", description="🏆 早く言った人トップ10", color=0xc0c0c0)
        for i, user_id in enumerate(user_rankings[:10]):
            timestamp = sorted_records[i][1].strftime('%H:%M:%S')
            embed.add_field(name=f"# {i+1} {mention_or_id(user_id)}", value=f"🕒 {timestamp}", inline=False)

        if interaction.user.id not in user_rankings[:10]:
            user_index = user_rankings.index(interaction.user.id)
            timestamp = akeome_records[interaction.user.id].strftime('%H:%M:%S')
            embed.add_field(name=" ", value=f"**あなたの順位**\n# {user_index+1} {interaction.user.mention} - 🕒 {timestamp}", inline=False)

        await interaction.response.send_message(embed=embed)

    elif another.value == "past":
        if not first_akeome_winners:
            await interaction.response.send_message("まだ一番乗りの記録がありません。", ephemeral=True)
            return

        counts = {}
        for uid in first_akeome_winners.values():
            counts[uid] = counts.get(uid, 0) + 1

        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        embed = discord.Embed(title="🏅 一番乗り回数ランキング", description="過去に一番乗りを獲得した回数", color=0xc0c0c0)

        for i, (user_id, count) in enumerate(sorted_counts[:10]):
            embed.add_field(name=f"# {i+1} {mention_or_id(user_id)}", value=f"🏆 {count} 回", inline=False)

        await interaction.response.send_message(embed=embed)

    elif another.value == "worst":
        if date_str not in akeome_history or not akeome_history[date_str]:
            await interaction.response.send_message("今日のあけおめ記録がありません。", ephemeral=True)
            return

        sorted_worst = sorted(akeome_history[date_str].items(), key=lambda x: x[1], reverse=True)
        embed = discord.Embed(title="🐢 今日のあけおめワースト10", description="遅く言った人ランキング", color=0xc0c0c0)

        for i, (user_id, timestamp) in enumerate(sorted_worst[:10]):
            time_str = timestamp.strftime('%H:%M:%S')
            embed.add_field(name=f"# {i+1} {mention_or_id(user_id)}", value=f"🐌 {time_str}", inline=False)

        await interaction.response.send_message(embed=embed)

client.run(TOKEN)
