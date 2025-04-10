import os
import discord
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.environ['DISCORD_TOKEN']

intents = discord.Intents.default()
# intents.threads = True
# intents.guilds = True
client = discord.Client(intents=intents)

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
    # テキストチャンネルかつ通常のメッセージの場合にのみ処理
    if isinstance(message.channel, discord.channel.TextChannel) and message.type == discord.MessageType.default:
        thread_name = message.content[:100].strip()  # 先頭100文字を取得し、前後の空白を削除
        if not thread_name:  # トリム後の文字列が空の場合の処理
            thread_name = "無題のスレッド"  # デフォルト名を設定するなど
        # メッセージの内容の先頭100文字（トリム後）をスレッド名に設定
        thread = await message.create_thread(name=thread_name, auto_archive_duration=10080)
        # スレッド作成後、Botはそのスレッドから退出する
        await thread.leave()

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
    print("discord.py v" + discord.__version__)

client.run(str(TOKEN))