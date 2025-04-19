#main.py
import os
import discord
from discord import app_commands
from dotenv import load_dotenv
from datetime import datetime, time, timezone, timedelta
import asyncio
import re

load_dotenv()
TOKEN = os.environ['DISCORD_TOKEN']

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
client = discord.Client(intents=intents)
client.presence_task_started = False
tree = app_commands.CommandTree(client)

first_new_year_message_sent_today = False
NEW_YEAR_WORD = "あけおめ"
akeome_records = {}  # {user_id: timestamp}

@client.event
async def on_ready():
    global first_new_year_message_sent_today
    print("Bot は準備完了です！")
    await tree.sync()
    first_new_year_message_sent_today = False

    if not client.presence_task_started:
        client.loop.create_task(update_presence())
        client.presence_task_started = True
        print("ステータス更新タスクを開始しました。")

    async def reset_daily_flag():
        global first_new_year_message_sent_today, akeome_records
        while True:
            now_jst = datetime.now(timezone(timedelta(hours=9)))
            tomorrow = now_jst.date() + timedelta(days=1)
            midnight_tomorrow = datetime.combine(tomorrow, time(0, 0, 0), tzinfo=timezone(timedelta(hours=9)))
            seconds_until_midnight = (midnight_tomorrow - now_jst).total_seconds()
            await asyncio.sleep(seconds_until_midnight)
            first_new_year_message_sent_today = False
            akeome_records = {}
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

    if isinstance(message.channel, discord.TextChannel) and message.type == discord.MessageType.default:
        if message.content.strip() == NEW_YEAR_WORD:
            if message.author.id not in akeome_records:
                akeome_records[message.author.id] = now_jst
                print(f"『{message.author.display_name}』のあけおめを記録しました。")

            if not first_new_year_message_sent_today:
                await message.channel.send(f"{message.author.mention} が一番乗り！あけましておめでとう！")
                first_new_year_message_sent_today = True

# スラッシュコマンドの実装
@tree.command(name="akeome_top", description="今日のあけおめトップ10と自分の順位を表示します")
async def akeome_top(interaction: discord.Interaction):
    now = datetime.now(timezone(timedelta(hours=9))).date()

    if not akeome_records:
        await interaction.response.send_message("今日はまだ誰も『あけおめ』していません！", ephemeral=True)
        return

    # タイムスタンプ順に並び替え
    sorted_records = sorted(akeome_records.items(), key=lambda x: x[1])
    user_rankings = [user_id for user_id, _ in sorted_records]

    embed = discord.Embed(title="📜 今日のあけおめランキング", description="🏆 早く言った人トップ10", color=0xc0c0c0)

    for i, user_id in enumerate(user_rankings[:10]):
        member = interaction.guild.get_member(user_id)
        name = member.display_name if member else f"ユーザーID:{user_id}"
        timestamp = sorted_records[i][1].strftime('%H:%M:%S')
        embed.add_field(name=f"# {i+1} {name}", value=f"🕒 {timestamp}", inline=False)

    # 実行者の順位（ランクインしてなければ別枠で）
    if interaction.user.id not in user_rankings[:10]:
        user_index = user_rankings.index(interaction.user.id)
        timestamp = akeome_records[interaction.user.id].strftime('%H:%M:%S')
        name = interaction.user.display_name
        embed.add_field(name=" ", value=f"**あなたの順位**\n# {user_index+1} {name} - 🕒 {timestamp}", inline=False)

    await interaction.response.send_message(embed=embed)

client.run(TOKEN)
