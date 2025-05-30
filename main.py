import os
import discord
from discord import app_commands
from dotenv import load_dotenv
from datetime import datetime, time, timezone, timedelta
import asyncio
import json
import re

load_dotenv()
TOKEN = os.environ['DISCORD_TOKEN']
DATA_FILE = "/data/akeome_data.json" # VScodeのときはdata/akeome_data.jsonに変更
# NorthFlankのときは/data/akeome_data.jsonに変更
intents = discord.Intents.all()
# intents.message_content = True # Ensure message content intent is enabled if not already covered by all() for your discord.py version
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

# ---------- Helper Function for Permission Check ----------
async def check_bot_specific_permission(guild: discord.Guild, channel: discord.abc.GuildChannel, permission_name: str) -> bool:
    """
    Checks if the bot's own integration role has a specific permission in the given channel.
    Args:
        guild: The guild where the permission is being checked.
        channel: The channel (TextChannel, VoiceChannel, etc.) where the permission applies.
        permission_name: The name of the permission attribute to check (e.g., "create_public_threads").
    Returns:
        True if the bot's specific role has the permission, False otherwise.
    """
    if not guild or not channel:
        return False
        
    bot_member = guild.me
    if not bot_member: # Should not happen if bot is in guild
        print(f"警告: Botメンバーオブジェクトがサーバー '{guild.name}' で見つかりません。")
        return False

    bot_integration_role = None
    for role in bot_member.roles:
        if role.tags and role.tags.bot_id == client.user.id:
            bot_integration_role = role
            break
    
    if not bot_integration_role:
        print(f"Botの固有ロールがサーバー '{guild.name}' で見つかりませんでした。権限 '{permission_name}' はありません。")
        return False

    permissions = channel.permissions_for(bot_integration_role)
    if not hasattr(permissions, permission_name):
        print(f"警告: 権限属性 '{permission_name}' はPermissionsオブジェクトに存在しません。")
        return False
        
    has_perm = getattr(permissions, permission_name)
    if not has_perm:
        # print(f"Botの固有ロール '{bot_integration_role.name}' にはチャンネル '{channel.name}' での '{permission_name}' 権限がありません。")
        pass # Avoid excessive logging for common denials, log only if role not found or attribute missing.
    return has_perm

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
        try:
            data = json.load(f)
            first_akeome_winners = data.get("first_akeome_winners", {})
            raw_history = data.get("akeome_history", {})
            for date_str_key, records in raw_history.items(): # Renamed 'date' to 'date_str_key'
                akeome_history[date_str_key] = { # Use 'date_str_key'
                    # Ensure uid is string if keys in JSON are strings, or handle conversion if they should be int
                    str(uid) if not isinstance(uid, int) else int(uid): datetime.fromisoformat(ts)
                    for uid, ts in records.items()
                }
            last_akeome_channel_id = data.get("last_akeome_channel_id")
        except json.JSONDecodeError:
            print(f"エラー: {DATA_FILE} のJSONデータの読み込みに失敗しました。空のデータで初期化します。")
            first_akeome_winners = {}
            akeome_history = {}
            last_akeome_channel_id = None


    if first_akeome_winners:
        try:
            # Filter out any non-date keys before finding min
            valid_dates = [key for key in first_akeome_winners.keys() if re.match(r'^\d{4}-\d{2}-\d{2}$', key)]
            if valid_dates:
                earliest_date_str = min(valid_dates)
                start_date = datetime.fromisoformat(earliest_date_str)
            else:
                start_date = None # No valid date keys found
        except Exception as e:
            print(f"開始日のパース中にエラー: {e}")
            start_date = None


async def unarchive_thread(thread: discord.Thread):
    """スレッドがアーカイブされていた場合に解除する"""
    if not thread.guild or not isinstance(thread.parent, discord.abc.GuildChannel):
        print(f"スレッド '{thread.name}' はギルドまたは親チャンネルのコンテキストが不足しているため、権限を確認できません。")
        return

    can_manage_threads = await check_bot_specific_permission(thread.guild, thread.parent, "manage_threads")
    if not can_manage_threads:
        print(f"Botの固有ロールにはスレッド管理権限がありません。スレッド '{thread.name}' のアーカイブを解除できません。チャンネル: '{thread.parent.name}'")
        return

    if thread.archived:
        try:
            await thread.edit(archived=False)
            print(f"スレッド '{thread.name}' のアーカイブを解除しました。")
        except discord.errors.NotFound:
            print(f"スレッド '{thread.name}' は見つかりませんでした。")
        except discord.errors.Forbidden:
            print(f"スレッド '{thread.name}' のアーカイブを解除する権限がありません（Forbidden）。")
        except Exception as e:
            print(f"スレッド '{thread.name}' のアーカイブ解除中にエラーが発生しました: {e}")

@client.event
async def on_thread_update(before: discord.Thread, after: discord.Thread):
    """スレッドの状態が更新された際に実行される"""
    if before.archived and not after.archived:
        # スレッドが既にアーカイブ解除された場合、または他の誰かによって解除された場合は何もしない
        return

    if not before.archived and after.archived:
        # スレッドがアーカイブされた場合、unarchive_threadを呼び出す
        # unarchive_thread内で権限チェックが行われる
        print(f"スレッド '{after.name}' がアーカイブされました。Botが解除すべきか確認します。")
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
            await asyncio.sleep(10) # エラー発生時は少し長めに待つ

async def reset_daily_flag():
    global first_new_year_message_sent_today, akeome_records
    while True:
        now_jst = datetime.now(timezone(timedelta(hours=9)))
        tomorrow = now_jst.date() + timedelta(days=1)
        midnight_tomorrow = datetime.combine(tomorrow, time(0, 0, 0), tzinfo=timezone(timedelta(hours=9)))
        seconds_until_midnight = (midnight_tomorrow - now_jst).total_seconds()
        
        if seconds_until_midnight < 0: # Just in case, if current time is past midnight but before loop adjusted
            seconds_until_midnight += 24 * 60 * 60

        await asyncio.sleep(seconds_until_midnight)
        first_new_year_message_sent_today = False
        akeome_records.clear() # akeome_records はその日の記録なのでクリア
        print("毎日のフラグと記録をリセットしました。")

async def reset_every_year():
    global start_date, first_akeome_winners # Ensure first_akeome_winners is global for clearing
    while True: # Loop to reschedule if start_date changes or bot restarts
        if not start_date:
            print("[定期リセット] 開始日が設定されていないため、年間リセットはスキップされます。5分後に再試行します。")
            await asyncio.sleep(300) # Wait 5 minutes and re-check
            continue

        now = datetime.now(timezone(timedelta(hours=9)))
        
        # Ensure start_date has timezone info for correct comparison
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone(timedelta(hours=9)))

        next_reset_year = now.year
        # If current month is already past start_date's month, or same month but past the day,
        # then next reset is for next year relative to start_date's year structure.
        # More simply: if now is after this year's anniversary of start_date, target next year's anniversary.
        
        # Construct this year's anniversary of start_date
        this_year_anniversary = start_date.replace(year=now.year)
        if now >= this_year_anniversary:
            next_reset_year = now.year + 1
        
        next_reset = start_date.replace(year=next_reset_year)

        if now >= next_reset: # If somehow current time is already past the calculated next_reset
            next_reset = start_date.replace(year=next_reset_year + 1)

        wait_seconds = (next_reset - now).total_seconds()
        print(f"[定期リセット] 次回リセットは {next_reset.isoformat()} に実行予定 (残り約 {wait_seconds/3600:.2f} 時間)")

        if wait_seconds < 0: # Should not happen with above logic, but as a safeguard
            print("[定期リセット] 計算された待機時間が負です。1時間後に再試行します。")
            await asyncio.sleep(3600)
            continue
            
        await asyncio.sleep(wait_seconds)

        # --- リセット実行 ---
        print(f"[定期リセット] {next_reset.isoformat()} になりました。一番乗り記録をリセットします。")
        if last_akeome_channel_id:
            channel = client.get_channel(last_akeome_channel_id)
            if channel and isinstance(channel, discord.TextChannel): # Ensure channel is TextChannel
                # Create counts for users who were first
                first_winner_counts = {}
                for date_key, winner_id in first_akeome_winners.items():
                    first_winner_counts[winner_id] = first_winner_counts.get(winner_id, 0) + 1
                
                sorted_counts = sorted(
                    first_winner_counts.items(),
                    key=lambda x: x[1], reverse=True
                )

                def get_name(uid):
                    member = channel.guild.get_member(int(uid)) # Ensure uid is int for get_member
                    return member.display_name if member else f"(ID: {uid})"

                lines = [
                    f"{i+1}. {get_name(uid)} 🏆 {count} 回"
                    for i, (uid, count) in enumerate(sorted_counts[:10])
                ]
                
                # Determine the period for the footer
                # start_date is the very first day a "first" was recorded.
                # end_date is the day before the reset.
                end_date_for_footer = next_reset - timedelta(days=1)
                footer_text = f"{start_date.strftime('%Y年%m月%d日')}から{end_date_for_footer.strftime('%Y年%m月%d日')}まで"
                
                embed = discord.Embed(title="🏅 一番乗り回数ランキング（年間リセット前）", description="\n".join(lines), color=0xc0c0c0)
                embed.set_footer(text=footer_text)
                
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    print(f"年間リセットランキングの送信権限がチャンネル ID {last_akeome_channel_id} にありません。")
                except Exception as e_send:
                    print(f"年間リセットランキングの送信中にエラー: {e_send}")
            else:
                print(f"年間リセット通知用のチャンネル ID {last_akeome_channel_id} が見つからないか、テキストチャンネルではありません。")


        first_akeome_winners.clear()
        # akeome_history is a historical log, should it be cleared annually?
        # Based on current logic, it's not cleared, only first_akeome_winners. This seems fine.
        save_data() # Save cleared first_akeome_winners
        print("[定期リセット] 一番乗り記録をリセットしました。")
        
        # Update start_date for the next cycle to be the date of this reset
        start_date = next_reset 
        # Loop will continue and recalculate wait for the *next* year's reset.


@client.event
async def on_message(message: discord.Message):
    global first_new_year_message_sent_today, last_akeome_channel_id, akeome_records, akeome_history, start_date

    if message.author == client.user:
        return
    
    if not message.guild: # Only operate in guilds
        return
    
    # Consolidated server exclusion check
    # 1364527180813566055 はテストサーバーIDの例です。実際のIDに置き換えてください。
    EXCLUDED_SERVER_ID = 1364527180813566055 
    if message.guild.id == EXCLUDED_SERVER_ID:
        # print(f"メッセージ受信サーバー ({message.guild.name}, ID: {message.guild.id}) は処理対象外のため、スレッド作成やあけおめ処理をスキップします。")
        return # Stop all processing for this server in on_message

    now_jst = datetime.now(timezone(timedelta(hours=9)))
    current_date_str = now_jst.date().isoformat()


    # --- Poll message thread creation ---
    if isinstance(message.channel, discord.TextChannel) and message.poll:
        can_create_threads = await check_bot_specific_permission(message.guild, message.channel, "create_public_threads")
        if can_create_threads:
            thread_name = message.poll.question[:100].strip() # discord.py v2 poll question is message.poll.question.text
            if hasattr(message.poll.question, 'text'): # For discord.py v2.x
                 thread_name = message.poll.question.text[:100].strip()
            else: # For older versions or if structure is just string
                 thread_name = str(message.poll.question)[:100].strip()


            fullwidth_space_match = re.search(r'　', thread_name)
            if fullwidth_space_match:
                thread_name = thread_name[:fullwidth_space_match.start()].strip()

            try:
                thread = await message.create_thread(name=thread_name if thread_name else "投票スレッド", auto_archive_duration=10080)
                print(f"投票メッセージからスレッドを作成しました。スレッド名: '{thread.name}'")
                
                can_add_reactions = await check_bot_specific_permission(message.guild, message.channel, "add_reactions")
                if can_add_reactions:
                    if message.channel.permissions_for(message.guild.me).read_message_history: # Bot needs history to react
                        try:
                            await message.add_reaction("✅")
                        except discord.errors.Forbidden:
                            print(f"Botの固有ロールには権限がありますが、リアクション追加（✅投票スレッド）に失敗しました（Forbidden）。")
                        except Exception as e_react:
                            print(f"リアクション追加中にエラーが発生しました（✅投票スレッド）: {e_react}")
                    else:
                        print(f"Botにはリアクション追加権限がありますが、メッセージ履歴読み取り権限がないためリアクションできません（投票スレッド）。")
                else:
                    print(f"Botの固有ロールにはリアクション追加権限がありません（投票スレッド）。チャンネル: '{message.channel.name}'")
            
            except discord.errors.Forbidden as e:
                print(f"投票メッセージからのスレッド作成中に権限エラーが発生しました (Forbidden): {e}。Botの固有ロールにスレッド作成権限がない可能性があります。")
            except discord.errors.HTTPException as e:
                print(f"投票メッセージからのスレッド作成中に HTTP エラーが発生しました: {e.status} {e.text if hasattr(e, 'text') else e.response}")
            except discord.errors.InvalidArgument as e:
                print(f"投票メッセージからのスレッド作成中に無効な引数エラーが発生しました: {e}")
            except Exception as e:
                print(f"投票メッセージからのスレッド作成中に予期しないエラーが発生しました: {e}")
        else:
            print(f"Botの固有ロールには「create_public_threads」権限がありません（投票メッセージ）。チャンネル: '{message.channel.name}'")
    
    # --- Normal message thread creation (POTENTIALLY PROBLEMATIC - CREATES THREAD FOR *EVERY* MESSAGE) ---
    # Consider removing or making this conditional (e.g., via a command)
    if isinstance(message.channel, discord.TextChannel) and \
       message.type == discord.MessageType.default and \
       message.content and not message.poll: # Ensure it's not a poll already handled

        can_create_threads_normal = await check_bot_specific_permission(message.guild, message.channel, "create_public_threads")
        if can_create_threads_normal:
            thread_name_normal = message.content[:100].strip()
            fullwidth_space_match_normal = re.search(r'　', thread_name_normal)
            if fullwidth_space_match_normal:
                thread_name_normal = thread_name_normal[:fullwidth_space_match_normal.start()].strip()

            try:
                # Avoid creating threads for very short or command-like messages unless intended
                if len(thread_name_normal) > 5 and not thread_name_normal.startswith(('!', '/', '$', '%')): # Basic filter
                    thread = await message.create_thread(name=thread_name_normal if thread_name_normal else "メッセージスレッド", auto_archive_duration=10080)
                    print(f"メッセージからスレッドを作成しました。スレッド名: '{thread.name}'")

                    can_add_reactions_normal = await check_bot_specific_permission(message.guild, message.channel, "add_reactions")
                    if can_add_reactions_normal:
                        if message.channel.permissions_for(message.guild.me).read_message_history:
                            try:
                                await message.add_reaction("✅")
                            except discord.errors.Forbidden:
                                print(f"Botの固有ロールには権限がありますが、リアクション追加（✅通常スレッド）に失敗しました（Forbidden）。")
                            except Exception as e_react:
                                print(f"リアクション追加中にエラーが発生しました（✅通常スレッド）: {e_react}")
                        else:
                            print(f"Botにはリアクション追加権限がありますが、メッセージ履歴読み取り権限がないためリアクションできません（通常スレッド）。")
                    else:
                        print(f"Botの固有ロールにはリアクション追加権限がありません（通常スレッド）。チャンネル: '{message.channel.name}'")
                # else:
                #     print(f"メッセージ「{thread_name_normal}」は短すぎるかコマンド形式のため、スレッドを作成しませんでした。")

            except discord.errors.Forbidden as e:
                print(f"メッセージからのスレッド作成中に権限エラーが発生しました (Forbidden): {e}。Botの固有ロールにスレッド作成権限がない可能性があります。")
            except discord.errors.HTTPException as e:
                print(f"メッセージからのスレッド作成中に HTTP エラーが発生しました: {e.status} {e.text if hasattr(e, 'text') else e.response}")
            except Exception as e:
                print(f"メッセージからのスレッド作成中に予期せぬエラーが発生しました: {e}")
        # else:
            # print(f"Botの固有ロールには「create_public_threads」権限がありません（通常メッセージ）。チャンネル: '{message.channel.name}'")
            # This log can be noisy if this block is active for all messages.

    # --- 「あけおめ」機能 ---
    if isinstance(message.channel, discord.TextChannel) and message.type == discord.MessageType.default:
        if message.content.strip() == NEW_YEAR_WORD:
            last_akeome_channel_id = message.channel.id
            author_id_str = str(message.author.id) # Use string for dict keys consistently

            if author_id_str not in akeome_records: # akeome_records stores daily first times by user
                akeome_records[author_id_str] = now_jst
                
                if current_date_str not in akeome_history:
                    akeome_history[current_date_str] = {}
                akeome_history[current_date_str][author_id_str] = now_jst
                # print(f"Akeome recorded for {message.author.name} on {current_date_str} at {now_jst.strftime('%H:%M:%S')}")
            
            if not first_new_year_message_sent_today: # This flag means "was the *absolute first* 'akeome' of the day sent by *anyone*?"
                can_send_messages = await check_bot_specific_permission(message.guild, message.channel, "send_messages")
                if can_send_messages:
                    try:
                        await message.channel.send(f"{message.author.mention} が一番乗り！あけましておめでとう！")
                    except discord.Forbidden:
                         print(f"一番乗りメッセージを送信できませんでした。Botの固有ロールに送信権限がありません（Forbidden）。チャンネル: '{message.channel.name}'")
                    except Exception as e_send:
                         print(f"一番乗りメッセージ送信中にエラー: {e_send}")
                else:
                    print(f"一番乗りメッセージを送信できません。Botの固有ロールに「send_messages」権限がありません。チャンネル: '{message.channel.name}'")
                
                first_new_year_message_sent_today = True
                first_akeome_winners[current_date_str] = author_id_str # Record who was first on this date
                
                if start_date is None: # If this is the very first "akeome" ever for this bot instance / data
                    start_date = now_jst.date() # Set start_date for yearly reset
                    print(f"初回のあけおめ記録。年間リセットの開始日を {start_date.isoformat()} に設定しました。")

            save_data() # Save after any potential update to akeome_history or first_akeome_winners

@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """リアクションが付与された際の処理"""
    if not payload.guild_id: # DMやグループなど、サーバー外のリアクションは無視
        return
    
    guild = client.get_guild(payload.guild_id)
    if not guild:
        return 
    
    member = guild.get_member(payload.user_id) # payload.member can be None
    if not member or member.bot:
        return

    if payload.emoji.name == "✅":
        channel = client.get_channel(payload.channel_id)
        if isinstance(channel, discord.TextChannel): # Ensure it's a text channel
            try:
                message = await channel.fetch_message(payload.message_id)
            except discord.NotFound:
                print(f"メッセージ {payload.message_id} が on_raw_reaction_add で見つかりませんでした。")
                return
            except discord.Forbidden:
                print(f"メッセージ {payload.message_id} の取得が on_raw_reaction_add で禁止されました。")
                return
            except Exception as e:
                print(f"メッセージ {payload.message_id} の取得中に on_raw_reaction_add でエラー: {e}")
                return

            # on_message内でサーバー除外と権限チェックが行われる
            # 注意: これによりon_messageの全ロジックが再実行される
            print(f"✅ リアクションが {member.display_name} によって追加されました。スレッド作成の可能性のため on_message に転送します。")
            await on_message(message)


@tree.command(name="akeome_top", description="今日のあけおめトップ10と自分の順位を表示します")
@app_commands.describe(another="他の集計結果も表示できます")
@app_commands.choices(another=[
    app_commands.Choice(name="過去の一番乗り回数ランキング", value="past"),
    app_commands.Choice(name="今日のワースト10", value="worst")
])
async def akeome_top(interaction: discord.Interaction, another: app_commands.Choice[str] = None):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    now = datetime.now(timezone(timedelta(hours=9)))
    date_str = now.date().isoformat()

    def get_display_name(user_id_str): # user_id is now string
        try:
            user_id_int = int(user_id_str)
            member = interaction.guild.get_member(user_id_int)
            return member.display_name if member else f"(ID: {user_id_str})"
        except ValueError:
            return f"(不明なID形式: {user_id_str})"


    def get_avatar_icon(user_id_str): # user_id is now string
        try:
            user_id_int = int(user_id_str)
            member = interaction.guild.get_member(user_id_int)
            return member.display_avatar.url if member and member.display_avatar else None
        except ValueError:
            return None

    def user_line(rank, user_id_str, symbol, extra): # user_id is now string
        icon_url = get_avatar_icon(user_id_str)
        name = get_display_name(user_id_str)
        # For discord.py 2.0, user.mention is preferred for linking if that's desired.
        # Here, we are constructing a markdown link if icon is available.
        if icon_url:
             # Markdown for image in embed is not standard. Usually, avatar is set via set_author or set_thumbnail.
             # Let's just display name and info.
             return f"{rank}. {name} {symbol} {extra}"
        return f"{rank}. {name} {symbol} {extra}"


    if another is None: # 今日のランキング
        if not akeome_records: # akeome_records stores today's records {user_id_str: datetime_obj}
            await interaction.response.send_message("今日はまだ誰も『あけおめ』していません！", ephemeral=True)
            return

        # Sort by time: value is datetime object
        sorted_today_records = sorted(akeome_records.items(), key=lambda x: x[1])
        
        lines = []
        user_found_in_top_10 = False
        user_rank_info = ""

        for i, (user_id_str, timestamp) in enumerate(sorted_today_records):
            rank = i + 1
            time_str = timestamp.strftime('%H:%M:%S.%f')[:-3] # Include milliseconds
            if rank <= 10:
                lines.append(user_line(rank, user_id_str, "🕒", time_str))
            if str(interaction.user.id) == user_id_str: # Compare as strings
                user_found_in_top_10 = (rank <= 10)
                user_rank_info = user_line(rank, user_id_str, '🕒', time_str)

        if not user_found_in_top_10 and str(interaction.user.id) in akeome_records:
            if not user_rank_info: # Should be populated if user is in akeome_records
                 # Find user's rank if not in top 10
                user_id_to_find = str(interaction.user.id)
                for i, (uid, ts) in enumerate(sorted_today_records):
                    if uid == user_id_to_find:
                        user_rank_info = user_line(i + 1, uid, '🕒', ts.strftime('%H:%M:%S.%f')[:-3])
                        break
            lines.append("")
            lines.append(f"あなたの順位\n{user_rank_info}")
        elif str(interaction.user.id) not in akeome_records:
             lines.append("\nあなたは今日まだ「あけおめ」していません。")


        embed = discord.Embed(title="📜 今日のあけおめランキング", description="\n".join(lines), color=0xc0c0c0)
        embed.set_footer(text=f"━━━ {now.strftime('%Y年%m月%d日')} ━━━")
        await interaction.response.send_message(embed=embed)

    elif another.value == "past": # 過去の一番乗り回数
        if not first_akeome_winners: # Stores {date_str: user_id_str}
            await interaction.response.send_message("まだ一番乗りの記録がありません。", ephemeral=True)
            return

        counts = {} # {user_id_str: count}
        for user_id_str in first_akeome_winners.values():
            counts[user_id_str] = counts.get(user_id_str, 0) + 1

        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        lines = []
        for i, (user_id_str, count) in enumerate(sorted_counts[:10]):
            lines.append(user_line(i + 1, user_id_str, "🏆", f"{count} 回"))

        footer_text = "集計期間: 全期間"
        if start_date: # start_date is a date object
            # end_date for "past" is effectively "today" or "up to the last record"
            # The yearly reset defines a clear period. For ongoing, it's up to now.
            # Let's use the period from start_date up to the last recorded 'first_akeome_winner' date if possible.
            if first_akeome_winners:
                last_recorded_date_str = max(first_akeome_winners.keys())
                last_recorded_date = datetime.fromisoformat(last_recorded_date_str).date()
                footer_text = f"{start_date.strftime('%Y年%m月%d日')}から{last_recorded_date.strftime('%Y年%m月%d日')}まで"
            else: # Should not happen if first_akeome_winners is not empty
                footer_text = f"{start_date.strftime('%Y年%m月%d日')}から現在まで"
        
        embed = discord.Embed(title="🏅 一番乗り回数ランキング（全期間累計）", description="\n".join(lines), color=0xc0c0c0)
        embed.set_footer(text=footer_text)
        await interaction.response.send_message(embed=embed)

    elif another.value == "worst": # 今日のワースト10
        if date_str not in akeome_history or not akeome_history[date_str]:
            await interaction.response.send_message("今日のあけおめ記録がありません。", ephemeral=True)
            return
        
        # akeome_history[date_str] is {user_id_str: datetime_obj}
        # Sort by time descending for worst
        sorted_worst = sorted(akeome_history[date_str].items(), key=lambda x: x[1], reverse=True)
        lines = []
        for i, (user_id_str, timestamp) in enumerate(sorted_worst[:10]):
            lines.append(user_line(i + 1, user_id_str, "🐌", timestamp.strftime('%H:%M:%S.%f')[:-3]))

        embed = discord.Embed(title="🐢 今日のあけおめワースト10", description="\n".join(lines), color=0xc0c0c0)
        embed.set_footer(text=f"━━━ {now.strftime('%Y年%m月%d日')} ━━━")
        await interaction.response.send_message(embed=embed)

client.run(TOKEN)
