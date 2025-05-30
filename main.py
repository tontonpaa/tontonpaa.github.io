import os
import discord
from discord import app_commands
from dotenv import load_dotenv
from datetime import datetime, time, timezone, timedelta
import asyncio
import json
import re

load_dotenv()
TOKEN = os.environ.get('DISCORD_TOKEN') # .get を使用して存在しない場合のエラーを防ぐ
DATA_FILE = os.environ.get('DISCORD_BOT_DATA_FILE', "/data/akeome_data.json") # 環境変数またはデフォルト値

# intents = discord.Intents.default() # 基本的なインテント
# intents.messages = True
# intents.guilds = True
# intents.message_content = True # メッセージ内容の取得に必要
# intents.reactions = True # リアクションイベント用
# intents.members = True # メンバー情報の取得に必要になる場合がある
intents = discord.Intents.all() # 開発中は all で、本番では必要なものに絞ることを推奨

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

# 通常メッセージからの自動スレッド作成を除外するチャンネルIDのリスト
# 例: AUTO_THREAD_EXCLUDED_CHANNELS = [123456789012345678, 987654321098765432]
AUTO_THREAD_EXCLUDED_CHANNELS = [] 

# ボットコマンドとみなす接頭辞のリスト
BOT_COMMAND_PREFIXES = ('!', '/', '$', '%', '#', '.', '?', ';', ',')

# ---------- Helper Function for Permission Check ----------
async def check_bot_permission(guild: discord.Guild, channel: discord.abc.GuildChannel, permission_name: str) -> bool:
    """
    ボットメンバーが指定されたチャンネルで特定の有効な権限を持っているか確認します。
    これにはロール権限とユーザー固有のチャンネル権限オーバーライドが含まれます。
    """
    if not guild or not channel:
        return False
        
    bot_member = guild.me 
    if not bot_member: 
        print(f"警告: Botメンバーオブジェクト (guild.me) がサーバー '{guild.name}' で見つかりません。")
        return False

    try:
        permissions = channel.permissions_for(bot_member) 
    except Exception as e:
        print(f"[権限エラー] チャンネル '{channel.name}' で Botメンバー '{bot_member.display_name}' の権限取得中にエラー: {e}")
        return False

    if not hasattr(permissions, permission_name):
        print(f"警告: 権限属性 '{permission_name}' はPermissionsオブジェクトに存在しません。チャンネル: '{channel.name}'")
        return False
        
    has_perm = getattr(permissions, permission_name)
    
    if not has_perm:
        print(f"[権限情報] Botメンバー '{bot_member.display_name}' の有効な権限では、チャンネル '{channel.name}' (サーバー: '{guild.name}') での '{permission_name}' が許可されていません。")
    return has_perm

# ---------- データ永続化 ----------
def save_data():
    # データ保存前にディレクトリが存在するか確認し、なければ作成
    data_dir = os.path.dirname(DATA_FILE)
    if data_dir and not os.path.exists(data_dir):
        try:
            os.makedirs(data_dir)
            print(f"データディレクトリを作成しました: {data_dir}")
        except OSError as e:
            print(f"データディレクトリ作成中にエラー: {e}")
            return # ディレクトリ作成に失敗したら保存処理を中断

    data = {
        "first_akeome_winners": first_akeome_winners,
        "akeome_history": {
            date_str: {uid: ts.isoformat() for uid, ts in recs.items()}
            for date_str, recs in akeome_history.items()
        },
        "last_akeome_channel_id": last_akeome_channel_id,
        "start_date": start_date.isoformat() if start_date else None # start_dateも保存
    }
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"データファイル '{DATA_FILE}' への書き込み中にエラー: {e}")
    except Exception as e:
        print(f"データ保存中に予期せぬエラー: {e}")


def load_data():
    global first_akeome_winners, akeome_history, last_akeome_channel_id, start_date
    if not os.path.exists(DATA_FILE):
        print(f"データファイル '{DATA_FILE}' が見つかりません。新規作成します。")
        # ファイルが存在しない場合、空のデータで初期化し、save_dataを呼んでファイルを作成
        first_akeome_winners = {}
        akeome_history = {}
        last_akeome_channel_id = None
        start_date = None
        save_data() # 空のファイルを作成
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            first_akeome_winners = data.get("first_akeome_winners", {})
            raw_history = data.get("akeome_history", {})
            akeome_history = {
                date_str: {str(uid): datetime.fromisoformat(ts) for uid, ts in recs.items()}
                for date_str, recs in raw_history.items()
            }
            last_akeome_channel_id = data.get("last_akeome_channel_id")
            start_date_str = data.get("start_date")
            if start_date_str:
                start_date = datetime.fromisoformat(start_date_str).date()
            else:
                start_date = None
            print(f"データファイル '{DATA_FILE}' を正常に読み込みました。")

    except json.JSONDecodeError:
        print(f"エラー: {DATA_FILE} のJSONデータの読み込みに失敗しました。データが破損している可能性があります。")
    except Exception as e:
        print(f"データ読み込み中に予期せぬエラー: {e}")

# ---------- スレッド関連 ----------
async def unarchive_thread_if_needed(thread: discord.Thread):
    if not thread.guild or not isinstance(thread.parent, discord.abc.GuildChannel):
        return

    can_manage_threads = await check_bot_permission(thread.guild, thread.parent, "manage_threads")
    if not can_manage_threads:
        return 

    if thread.archived:
        try:
            await thread.edit(archived=False)
            print(f"スレッド '{thread.name}' (ID: {thread.id}) のアーカイブを解除しました。")
        except discord.NotFound:
            print(f"スレッド '{thread.name}' (ID: {thread.id}) は見つかりませんでした（アーカイブ解除試行時）。")
        except discord.Forbidden:
            print(f"スレッド '{thread.name}' (ID: {thread.id}) のアーカイブを解除する権限がありません（Forbidden）。")
        except Exception as e:
            print(f"スレッド '{thread.name}' (ID: {thread.id}) のアーカイブ解除中にエラー: {e}")

@client.event
async def on_thread_update(before: discord.Thread, after: discord.Thread):
    if before.archived and not after.archived: # 既に誰かが解除した場合
        return
    if not before.archived and after.archived: # アーカイブされた場合
        # print(f"スレッド '{after.name}' (ID: {after.id}) がアーカイブされました。解除を試みます。")
        await unarchive_thread_if_needed(after)

# ---------- 定期処理 ----------
@client.event
async def on_ready():
    global first_new_year_message_sent_today
    print(f"--- {client.user.name} (ID: {client.user.id}) 準備完了 ---")
    try:
        synced = await tree.sync()
        if synced:
            print(f"{len(synced)}個のスラッシュコマンドを同期しました: {[s.name for s in synced]}")
        else:
            print("スラッシュコマンドの同期対象がありませんでした。")
    except Exception as e:
        print(f"スラッシュコマンド同期中にエラー: {e}")
    
    load_data() # 起動時にデータをロード

    now = datetime.now(timezone(timedelta(hours=9)))
    date_str = now.date().isoformat()
    first_new_year_message_sent_today = date_str in first_akeome_winners

    if not client.presence_task_started:
        client.loop.create_task(update_presence_periodically())
        client.loop.create_task(reset_daily_flags_at_midnight())
        client.loop.create_task(reset_yearly_records_on_anniversary())
        client.presence_task_started = True
    print("--- 初期化処理完了 ---")

async def update_presence_periodically():
    await client.wait_until_ready() # Botが完全に準備できるまで待つ
    while not client.is_closed():
        try:
            ping = round(client.latency * 1000)
            activity1 = discord.Game(name=f"Ping: {ping}ms")
            await client.change_presence(activity=activity1)
            await asyncio.sleep(20) 

            if client.guilds: 
                activity2 = discord.Game(name=f"サーバー数: {len(client.guilds)}")
                await client.change_presence(activity=activity2)
                await asyncio.sleep(20)
            else: # 参加サーバーがない場合
                await asyncio.sleep(20) # Ping表示のまま待機

        except asyncio.CancelledError:
            print("プレゼンス更新タスクがキャンセルされました。")
            break
        except Exception as e:
            print(f"[update_presence エラー] {e}")
            await asyncio.sleep(60)

async def reset_daily_flags_at_midnight():
    global first_new_year_message_sent_today, akeome_records
    await client.wait_until_ready()
    while not client.is_closed():
        now_jst = datetime.now(timezone(timedelta(hours=9)))
        tomorrow_date = now_jst.date() + timedelta(days=1) 
        midnight_tomorrow = datetime.combine(tomorrow_date, time(0, 0, 0), tzinfo=timezone(timedelta(hours=9)))
        seconds_until_midnight = (midnight_tomorrow - now_jst).total_seconds()
        
        if seconds_until_midnight < 0: 
            seconds_until_midnight += 24 * 60 * 60 # 既に0時を過ぎていた場合の補正

        await asyncio.sleep(max(1, seconds_until_midnight)) # 最低1秒は待つ
        
        first_new_year_message_sent_today = False
        akeome_records.clear() 
        print(f"[{datetime.now(timezone(timedelta(hours=9))):%Y-%m-%d %H:%M:%S}] 毎日のフラグと「あけおめ」記録をリセットしました。")
        save_data() # リセット後も保存

async def reset_yearly_records_on_anniversary():
    global start_date, first_akeome_winners
    await client.wait_until_ready()
    while not client.is_closed():
        if not start_date:
            # print("[年間リセット] 開始日が未設定のため待機します。")
            await asyncio.sleep(3600) # 1時間後に再チェック
            continue

        now_utc = datetime.now(timezone.utc) # JSTではなくUTCで統一して計算
        # start_date は date オブジェクトなので、時分秒は0時0分0秒として扱う
        # JSTの0時0分はUTCの前日15時なので、リセットタイミングを明確にするためJST基準で計算
        
        now_jst_for_calc = datetime.now(timezone(timedelta(hours=9)))

        # start_date (date object) から今年の記念日 (datetime object, JST) を作成
        try:
            current_year_anniversary_jst = datetime(now_jst_for_calc.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=timezone(timedelta(hours=9)))
        except ValueError: # 閏年の2/29など、該当日がない場合
            print(f"[年間リセット] 開始日 {start_date.month}/{start_date.day} は今年存在しません。翌日を試みます。")
            # 簡単のため、翌月の1日を記念日とするなどの代替ロジックが必要になる場合がある
            # ここでは単純に次のチェックまで待つ
            await asyncio.sleep(24 * 3600) # 1日待つ
            continue

        next_reset_anniversary_jst = current_year_anniversary_jst
        if now_jst_for_calc >= current_year_anniversary_jst:
            # 今年の記念日が既に過ぎていれば、来年の記念日を次のリセット日とする
            try:
                next_reset_anniversary_jst = current_year_anniversary_jst.replace(year=current_year_anniversary_jst.year + 1)
            except ValueError: # 来年の該当日がない場合（例: 2/29の翌年）
                 next_reset_anniversary_jst = current_year_anniversary_jst.replace(year=current_year_anniversary_jst.year + 1, day=28)


        wait_seconds = (next_reset_anniversary_jst - now_jst_for_calc).total_seconds()
        
        # print(f"[年間リセット] 次回リセット予定: {next_reset_anniversary_jst.isoformat()} (JST) (残り約 {wait_seconds/3600:.2f} 時間)")

        if wait_seconds <= 0: # 計算結果が過去または即時実行の場合
            # print("[年間リセット] 待機時間が0以下です。即時リセット処理へ。")
            pass # そのままリセット処理へ
        else:
            await asyncio.sleep(wait_seconds)

        print(f"[{datetime.now(timezone(timedelta(hours=9))):%Y-%m-%d %H:%M:%S}] 年間リセットタイミングです。一番乗り記録を処理します。")
        
        # ランキング通知処理
        if last_akeome_channel_id and first_akeome_winners: # 記録がある場合のみ通知
            target_channel = client.get_channel(last_akeome_channel_id)
            if target_channel and isinstance(target_channel, discord.TextChannel):
                # (ランキング通知のロジックは変更なし)
                first_winner_counts_yearly = {}
                for winner_id_str_yearly in first_akeome_winners.values(): 
                    first_winner_counts_yearly[winner_id_str_yearly] = first_winner_counts_yearly.get(winner_id_str_yearly, 0) + 1
                
                sorted_counts_yearly = sorted(first_winner_counts_yearly.items(), key=lambda x_yearly: x_yearly[1], reverse=True)

                def get_name_yearly(uid_str_yearly, guild_context_yearly): 
                    try:
                        member_yearly = guild_context_yearly.get_member(int(uid_str_yearly))
                        return member_yearly.display_name if member_yearly else f"(ID: {uid_str_yearly})"
                    except ValueError:
                        return f"(不明なID: {uid_str_yearly})"

                lines_yearly = [
                    f"{i_yearly+1}. {get_name_yearly(uid_str_yearly, target_channel.guild)} 🏆 {count_yearly} 回"
                    for i_yearly, (uid_str_yearly, count_yearly) in enumerate(sorted_counts_yearly[:10])
                ]
                
                end_date_for_footer_yearly = next_reset_anniversary_jst.date() - timedelta(days=1)
                footer_text_yearly = f"{start_date.strftime('%Y年%m月%d日')}から{end_date_for_footer_yearly.strftime('%Y年%m月%d日')}まで"
                
                embed_yearly = discord.Embed(title="🏅 一番乗り回数ランキング（年間リセット前）", description="\n".join(lines_yearly) if lines_yearly else "該当者なし", color=0xc0c0c0)
                embed_yearly.set_footer(text=footer_text_yearly)
                
                try:
                    await target_channel.send(embed=embed_yearly)
                except discord.Forbidden:
                    print(f"年間リセットランキングの送信権限がチャンネル ID {last_akeome_channel_id} にありません。")
                except Exception as e_send_yearly:
                    print(f"年間リセットランキングの送信中にエラー: {e_send_yearly}")


        # 記録クリアと日付更新
        first_akeome_winners.clear()
        new_start_date = next_reset_anniversary_jst.date() # リセット日を新しい開始日とする
        print(f"[年間リセット] 一番乗り記録をクリアしました。新しい開始日: {new_start_date.isoformat()}")
        start_date = new_start_date # グローバル変数を更新
        save_data() # 変更を保存

# ---------- メッセージ処理 ----------
@client.event
async def on_message(message: discord.Message):
    global first_new_year_message_sent_today, last_akeome_channel_id, akeome_records, akeome_history, start_date

    if message.author == client.user or message.author.bot: # Bot自身のメッセージと他のBotのメッセージは無視
        return
    
    if not message.guild: # DMは無視
        return
    
    # 特定のサーバーIDを除外するロジックはここから削除されました。

    now_jst = datetime.now(timezone(timedelta(hours=9)))
    current_date_str = now_jst.date().isoformat()

    # --- 投票メッセージからのスレッド作成 ---
    if isinstance(message.channel, discord.TextChannel) and message.poll:
        can_create_threads_poll = await check_bot_permission(message.guild, message.channel, "create_public_threads")
        if can_create_threads_poll:
            poll_question_text = "投票スレッド" # デフォルト
            if hasattr(message.poll, 'question'):
                if isinstance(message.poll.question, str):
                    poll_question_text = message.poll.question
                elif hasattr(message.poll.question, 'text') and isinstance(message.poll.question.text, str):
                     poll_question_text = message.poll.question.text
            
            thread_name = poll_question_text[:100].strip()
            fullwidth_space_match = re.search(r'　', thread_name) # 全角スペースで区切る
            if fullwidth_space_match:
                thread_name = thread_name[:fullwidth_space_match.start()].strip()
            thread_name = thread_name if thread_name else "投票に関するスレッド" # 空文字対策

            try:
                thread = await message.create_thread(name=thread_name, auto_archive_duration=10080) # 1週間
                print(f"投票メッセージからスレッドを作成: '{thread.name}' (チャンネル: {message.channel.name})")
                
                can_add_reactions_poll = await check_bot_permission(message.guild, message.channel, "add_reactions")
                if can_add_reactions_poll:
                    await message.add_reaction("✅")
            except Exception as e:
                print(f"投票スレッド作成/リアクション中にエラー: {e} (チャンネル: {message.channel.name})")
    
    # --- 通常メッセージからのスレッド作成 (条件付き) ---
    elif isinstance(message.channel, discord.TextChannel) and \
         message.type == discord.MessageType.default and \
         message.content: # message.content があること (添付ファイルのみなどは除く)
        
        # 特定チャンネルでは自動スレッド作成をスキップ
        if message.channel.id in AUTO_THREAD_EXCLUDED_CHANNELS:
            return

        content_stripped = message.content.strip()
        
        # 2. ボットコマンド接頭辞で始まる場合はスキップ
        if content_stripped.startswith(BOT_COMMAND_PREFIXES):
            return

        # 4. スレッド作成権限の確認
        can_create_threads_normal = await check_bot_permission(message.guild, message.channel, "create_public_threads")
        if not can_create_threads_normal:
            return

        # 条件を満たした場合、スレッド作成処理
        thread_name_normal = content_stripped[:80].strip() # スレッド名をメッセージ内容の先頭80文字に
        thread_name_normal = re.sub(r'[\\/*?"<>|:]', '', thread_name_normal) # スレッド名に使えない文字の除去
        thread_name_normal = thread_name_normal if thread_name_normal else "関連スレッド"

        try:
            thread = await message.create_thread(name=thread_name_normal, auto_archive_duration=10080)
            print(f"通常メッセージ「{content_stripped[:30]}...」からスレッドを作成: '{thread.name}' (チャンネル: {message.channel.name})")

            can_add_reactions_normal = await check_bot_permission(message.guild, message.channel, "add_reactions")
            if can_add_reactions_normal:
                await message.add_reaction("💬") # 通常メッセージからのスレッドは絵文字を変更
        except discord.errors.HTTPException as e:
            if e.status == 400 and e.code == 50035 : 
                 print(f"通常スレッド作成失敗(400): スレッド名「{thread_name_normal}」が無効の可能性。詳細: {e.text}")
            else:
                 print(f"通常スレッド作成/リアクション中にHTTPエラー: {e} (チャンネル: {message.channel.name})")
        except Exception as e:
            print(f"通常スレッド作成/リアクション中に予期せぬエラー: {e} (チャンネル: {message.channel.name})")


    # --- 「あけおめ」機能 ---
    if isinstance(message.channel, discord.TextChannel) and message.type == discord.MessageType.default:
        if message.content.strip() == NEW_YEAR_WORD:
            last_akeome_channel_id = message.channel.id
            author_id_str = str(message.author.id) 

            if author_id_str not in akeome_records: 
                akeome_records[author_id_str] = now_jst
                
                if current_date_str not in akeome_history:
                    akeome_history[current_date_str] = {}
                akeome_history[current_date_str][author_id_str] = now_jst
            
            if not first_new_year_message_sent_today: 
                can_send_messages_akeome = await check_bot_permission(message.guild, message.channel, "send_messages")
                if can_send_messages_akeome:
                    try:
                        await message.channel.send(f"{message.author.mention} が一番乗り！あけましておめでとう！")
                    except Exception as e_send:
                         print(f"一番乗りメッセージ送信中にエラー: {e_send}。チャンネル: '{message.channel.name}'")
                
                first_new_year_message_sent_today = True
                first_akeome_winners[current_date_str] = author_id_str
                
                if start_date is None: 
                    start_date = now_jst.date() 
                    print(f"初回の「あけおめ」記録。年間リセットの基準日を {start_date.isoformat()} に設定しました。")
            save_data() # あけおめ記録後も保存

@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if not payload.guild_id: 
        return
    
    guild = client.get_guild(payload.guild_id)
    if not guild: return 
    
    try:
        member = payload.member or await guild.fetch_member(payload.user_id)
    except (discord.NotFound, discord.HTTPException): return

    if not member or member.bot: return

    if payload.emoji.name == "✅": 
        channel = client.get_channel(payload.channel_id)
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(payload.message_id)
                # await on_message(message) # 必要に応じてコメント解除し、リアクション起因のスレッド作成を検討
            except (discord.NotFound, discord.Forbidden): return
            except Exception as e:
                print(f"リアクションからのメッセージ取得エラー: {e}")


# ---------- スラッシュコマンド ----------
@tree.command(name="akeome_top", description="今日の「あけおめ」トップ10と自分の順位を表示します。")
@app_commands.describe(another="他の集計結果も表示できます（オプション）")
@app_commands.choices(another=[
    app_commands.Choice(name="過去の一番乗り回数ランキング", value="past_winners"),
    app_commands.Choice(name="今日のワースト10（遅かった人）", value="today_worst")
])
async def akeome_top_command(interaction: discord.Interaction, another: app_commands.Choice[str] = None):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    now_jst_cmd = datetime.now(timezone(timedelta(hours=9)))
    current_date_str_cmd = now_jst_cmd.date().isoformat()

    def get_member_display_name(user_id_str):
        try:
            member = interaction.guild.get_member(int(user_id_str))
            return member.display_name if member else f"ID: {user_id_str}"
        except (ValueError, TypeError):
            return f"不明なID: {user_id_str}"

    def format_user_line(rank, uid, time_or_count_str, icon="🕒"):
        name = get_member_display_name(uid)
        return f"{rank}. {name} {icon} {time_or_count_str}"

    embed = discord.Embed(color=0xc0c0c0)
    embed.set_footer(text=f"集計日時: {now_jst_cmd.strftime('%Y年%m月%d日 %H:%M:%S')}")

    if another is None or not another.value: 
        embed.title = "📜 今日の「あけおめ」ランキング"
        if not akeome_records:
            embed.description = "今日はまだ誰も「あけおめ」していません！"
        else:
            sorted_today = sorted(akeome_records.items(), key=lambda item: item[1])
            lines = [format_user_line(i+1, uid, ts.strftime('%H:%M:%S.%f')[:-3]) for i, (uid, ts) in enumerate(sorted_today[:10])]
            
            user_id_str_cmd = str(interaction.user.id)
            if user_id_str_cmd in akeome_records:
                user_rank = -1
                for i, (uid, ts) in enumerate(sorted_today):
                    if uid == user_id_str_cmd:
                        user_rank = i + 1
                        break
                if user_rank != -1 and user_rank > 10: 
                    lines.append("...")
                    lines.append(format_user_line(user_rank, user_id_str_cmd, akeome_records[user_id_str_cmd].strftime('%H:%M:%S.%f')[:-3]))
            else:
                lines.append("\nあなたは今日まだ「あけおめ」していません。")
            embed.description = "\n".join(lines) if lines else "記録がありません。"

    elif another.value == "past_winners":
        embed.title = "🏅 過去の一番乗り回数ランキング"
        if not first_akeome_winners:
            embed.description = "まだ一番乗りの記録がありません。"
        else:
            winner_counts = {}
            for uid_winner in first_akeome_winners.values():
                winner_counts[uid_winner] = winner_counts.get(uid_winner, 0) + 1
            
            sorted_past = sorted(winner_counts.items(), key=lambda item: item[1], reverse=True)
            lines = [format_user_line(i+1, uid, f"{count} 回", "🏆") for i, (uid, count) in enumerate(sorted_past[:10])]
            embed.description = "\n".join(lines) if lines else "記録がありません。"
            if start_date and first_akeome_winners:
                try:
                    last_win_date_str = max(d for d in first_akeome_winners.keys() if re.match(r'^\d{4}-\d{2}-\d{2}$', d))
                    last_win_date = datetime.fromisoformat(last_win_date_str).date()
                    embed.set_footer(text=f"集計期間: {start_date.strftime('%Y/%m/%d')} ～ {last_win_date.strftime('%Y/%m/%d')}")
                except: pass 

    elif another.value == "today_worst":
        embed.title = "🐢 今日の「あけおめ」ワースト10 (遅かった順)"
        today_history = akeome_history.get(current_date_str_cmd, {})
        if not today_history:
            embed.description = "今日の「あけおめ」記録がありません。"
        else:
            sorted_worst = sorted(today_history.items(), key=lambda item: item[1], reverse=True)
            lines = [format_user_line(i+1, uid, ts.strftime('%H:%M:%S.%f')[:-3], "🐌") for i, (uid, ts) in enumerate(sorted_worst[:10])]
            embed.description = "\n".join(lines) if lines else "記録がありません。"
            
    await interaction.response.send_message(embed=embed)


# ---------- Bot実行 ----------
if __name__ == "__main__":
    if TOKEN is None:
        print("エラー: Discord Botのトークンが設定されていません。環境変数 'DISCORD_TOKEN' を設定してください。")
    else:
        try:
            print("Botを起動します...")
            client.run(TOKEN)
        except discord.PrivilegedIntentsRequired:
            print("エラー: Botに必要な特権インテント（Privileged Intents）が有効になっていません。")
            print("Discord Developer Portal (https://discord.com/developers/applications) で、")
            print("お使いのBotのページを開き、'Privileged Gateway Intents' セクションの")
            print("'MESSAGE CONTENT INTENT' を有効にしてください。")
            print("また、'SERVER MEMBERS INTENT' も有効にすると、より多くの機能が安定して動作する場合があります。")
        except Exception as e:
            print(f"Botの実行中に致命的なエラーが発生しました: {type(e).__name__} - {e}")

