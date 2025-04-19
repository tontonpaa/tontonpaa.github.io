#main.py
import os
import discord
from dotenv import load_dotenv
from datetime import datetime, time, timezone, timedelta
import asyncio
import re  # 正規表現モジュールを追加

load_dotenv()

TOKEN = os.environ['DISCORD_TOKEN']

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

first_new_year_message_sent_today = False
NEW_YEAR_WORD = "あけおめ"

async def update_presence():
    """Botのステータスを定期的に更新する"""
    while True:
        try:
            ping = round(client.latency * 1000)
            activity_ping = discord.Game(name=f"Ping: {ping}ms")
            await client.change_presence(activity=activity_ping)
            await asyncio.sleep(5)

            guild_count = len(client.guilds)
            activity_servers = discord.Game(name=f"サーバー数: {guild_count}")
            await client.change_presence(activity=activity_servers)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[update_presence エラー] {e}")
            await asyncio.sleep(10)  # 失敗時も落ちないように待機してリトライ

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

@client.event
async def on_message(message):
    global first_new_year_message_sent_today
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    today = now_jst.date()
    midnight_jst = datetime.combine(today, time(0, 0, 0), tzinfo=timezone(timedelta(hours=9)))

    print(f"on_message イベントが発生しました。")
    print(f"message.author: {message.author}")
    print(f"message.channel の型: {type(message.channel)}")
    print(f"message.channel: {message.channel}")
    print(f"message.type: {message.type}")
    print(f"message.content の値 (raw): '{message.content}'")

    # Bot自身のメッセージの場合は処理をスキップ
    if message.author == client.user:
        print("Bot自身のメッセージのため、処理をスキップします。")
        return

    # 毎日最初の「あけおめ」メッセージへの反応
    if isinstance(message.channel, discord.channel.TextChannel) and message.type == discord.MessageType.default and message.content == NEW_YEAR_WORD:
        if not first_new_year_message_sent_today:
            response = f"{message.author.mention} が一番乗り！あけましておめでとう！"
            try:
                await message.channel.send(response)
                print(f"「あけおめ」一番乗りメッセージを送信しました: {response}")
                first_new_year_message_sent_today = True
            except discord.errors.Forbidden as e:
                print(f"「あけおめ」メッセージ送信中に権限エラーが発生しました: {e}")
            except Exception as e:
                print(f"「あけおめ」メッセージ送信中に予期せぬエラーが発生しました: {e}")

    # テキストチャンネルかつ通常のメッセージの場合に処理 (スレッド作成機能)
    if isinstance(message.channel, discord.channel.TextChannel) and message.type == discord.MessageType.default:
        if message.content:
            # ここで再度 content を確認
            print(f"message.content (処理直前): '{message.content}'")
            thread_name = message.content[:100].strip()  # 先頭100文字を取得し、前後の空白を削除

            # 全角スペースを検索し、その直前までをスレッド名にする
            fullwidth_space_match = re.search(r'　', thread_name)
            if fullwidth_space_match:
                thread_name = thread_name[:fullwidth_space_match.start()].strip()
                print(f"全角スペースを検知しました。スレッド名 (処理後): '{thread_name}'")
            else:
                print(f"thread_name (処理後): '{thread_name}'")

            try:
                # メッセージの内容（または全角スペースまでの部分）をスレッド名に設定
                thread = await message.create_thread(name=thread_name, auto_archive_duration=10080)
                print(f"スレッドを作成しました。スレッド名: '{thread.name}'")
                await message.add_reaction("✅")  # スレッド作成元のメッセージに✅を付与
                # await thread.leave()
            except discord.errors.Forbidden as e:
                print(f"スレッド作成中に権限エラーが発生しました: {e}")
            except discord.errors.HTTPException as e:
                print(f"スレッド作成中に HTTP エラーが発生しました: {e}")
            except Exception as e:
                print(f"スレッド作成中に予期せぬエラーが発生しました: {e}")
        else:
            print("メッセージ内容が空のため、スレッド作成をスキップします。")

@client.event
async def on_message_delete(message):
    """メッセージが削除された際に実行される"""
    # Botが送信したスレッド作成時の自動メッセージを検出して削除
    if message.author == client.user and message.content.endswith("すべてのスレッドを見る場合はこちら。"):
        try:
            await message.delete()
            print(f"自動メッセージ '{message.content}' を削除しました。")
        except discord.errors.NotFound:
            print("削除しようとしたメッセージは見つかりませんでした。")
        except discord.errors.Forbidden:
            print("メッセージを削除する権限がありません。")
        except Exception as e:
            print(f"自動メッセージの削除中にエラーが発生しました: {e}")

@client.event
async def on_ready():
    global first_new_year_message_sent_today
    print("discord.py v" + discord.__version__)
    print("Bot は準備完了です！")
    first_new_year_message_sent_today = False # Bot起動時にフラグをリセット
    if not client.presence_task_started:
        client.loop.create_task(update_presence())
        client.presence_task_started = True
        print("ステータス更新タスクを開始しました。")
    else:
        print("ステータス更新タスクはすでに開始されています。")

    async def reset_daily_flag():
        global first_new_year_message_sent_today
        while True:
            now_jst = datetime.now(timezone(timedelta(hours=9)))
            tomorrow = now_jst.date() + timedelta(days=1)
            midnight_tomorrow = datetime.combine(tomorrow, time(0, 0, 0), tzinfo=timezone(timedelta(hours=9)))
            seconds_until_midnight = (midnight_tomorrow - now_jst).total_seconds()
            await asyncio.sleep(seconds_until_midnight)
            first_new_year_message_sent_today = False
            print("毎日のフラグをリセットしました。")

    client.loop.create_task(reset_daily_flag())

client.run(str(TOKEN))