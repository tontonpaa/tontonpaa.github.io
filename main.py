import os
import discord
from discord import app_commands
from dotenv import load_dotenv
from datetime import datetime, time, timezone, timedelta
import asyncio
import json
import re

load_dotenv()
TOKEN = os.environ.get('DISCORD_TOKEN') 
DATA_FILE = os.environ.get('DISCORD_BOT_DATA_FILE', "/data/akeome_data.json") 

intents = discord.Intents.all()

client = discord.Client(intents=intents)
client.presence_task_started = False
start_date = None 

tree = app_commands.CommandTree(client)

first_new_year_message_sent_today = False
NEW_YEAR_WORD = "あけおめ"

akeome_records = {}
first_akeome_winners = {}
akeome_history = {}
last_akeome_channel_id = None

AUTO_THREAD_EXCLUDED_CHANNELS = [] 
BOT_COMMAND_PREFIXES = ('!', '/', '$', '%', '#', '.', '?', ';', ',')

# ---------- Helper Function for Permission Check (Stricter) ----------
async def check_bot_permission(guild: discord.Guild, channel: discord.abc.GuildChannel, permission_name: str) -> bool:
    """
    ボット自身またはボットの統合ロールに、チャンネルオーバーライドまたは
    （統合ロールの）基本権限として明示的な許可がある場合のみ True を返します。
    @everyone ロールの設定には依存しません。
    """
    if not guild or not channel:
        return False
        
    bot_member = guild.me 
    if not bot_member: 
        print(f"警告: Botメンバーオブジェクト (guild.me) がサーバー '{guild.name}' で見つかりません。")
        return False

    # 1. ボット自身へのチャンネルオーバーライドを確認
    # discord.py v2.x では PermissionOverwrite オブジェクトのプロパティとして権限にアクセス
    bot_overwrite = channel.overwrites_for(bot_member)
    bot_explicit_perm_value = getattr(bot_overwrite, permission_name, None)

    if bot_explicit_perm_value is True: # 明示的に許可 (True)
        # print(f"[権限情報(Strict)] Botメンバー '{bot_member.display_name}' はチャンネル '{channel.name}' のオーバーライドで '{permission_name}' を明示的に許可されています。")
        return True
    if bot_explicit_perm_value is False: # 明示的に拒否 (False)
        print(f"[権限情報(Strict)] Botメンバー '{bot_member.display_name}' はチャンネル '{channel.name}' のオーバーライドで '{permission_name}' を明示的に拒否されています。動作しません。")
        return False
    # bot_explicit_perm_value が None の場合は、オーバーライドなし。次に進む。

    # 2. ボットの統合ロールの権限を確認
    bot_integration_role = None
    for role in bot_member.roles:
        if role.tags and role.tags.bot_id == client.user.id: # ボットの統合ロールか確認
            bot_integration_role = role
            break
            
    if bot_integration_role:
        # 統合ロールのチャンネルオーバーライドを確認
        role_overwrite = channel.overwrites_for(bot_integration_role)
        role_explicit_perm_value = getattr(role_overwrite, permission_name, None)

        if role_explicit_perm_value is True: # 明示的に許可
            # print(f"[権限情報(Strict)] Bot統合ロール '{bot_integration_role.name}' はチャンネル '{channel.name}' のオーバーライドで '{permission_name}' を明示的に許可されています。")
            return True
        if role_explicit_perm_value is False: # 明示的に拒否
            print(f"[権限情報(Strict)] Bot統合ロール '{bot_integration_role.name}' はチャンネル '{channel.name}' のオーバーライドで '{permission_name}' を明示的に拒否されています。動作しません。")
            return False
        # role_explicit_perm_value が None の場合は、オーバーライドなし。次にロールの基本権限を見る。

        # 統合ロールの基本権限 (サーバー設定)
        # role.permissions はそのロール自体の権限設定を直接示す
        if getattr(bot_integration_role.permissions, permission_name, False):
            # print(f"[権限情報(Strict)] Bot統合ロール '{bot_integration_role.name}' の基本権限で '{permission_name}' が許可されています (チャンネルオーバーライドなし)。")
            return True
    
    # 上記のいずれにも該当しない場合、ボット固有の明示的な許可はないと判断
    print(f"[権限情報(Strict)] Botメンバー '{bot_member.display_name}' (またはその統合ロール) には、チャンネル '{channel.name}' での '{permission_name}' に対する明示的な許可設定が見つかりませんでした。動作しません。")
    return False

# ---------- データ永続化 ----------
def save_data():
    data_dir = os.path.dirname(DATA_FILE)
    if data_dir and not os.path.exists(data_dir):
        try:
            os.makedirs(data_dir)
            print(f"データディレクトリを作成しました: {data_dir}")
        except OSError as e:
            print(f"データディレクトリ作成中にエラー: {e}")
            return

    data = {
        "first_akeome_winners": first_akeome_winners,
        "akeome_history": {
            date_str: {uid: ts.isoformat() for uid, ts in recs.items()}
            for date_str, recs in akeome_history.items()
        },
        "last_akeome_channel_id": last_akeome_channel_id,
        "start_date": start_date.isoformat() if start_date else None
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
        first_akeome_winners = {}
        akeome_history = {}
        last_akeome_channel_id = None
        start_date = None
        save_data() 
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
            # print(f"データファイル '{DATA_FILE}' を正常に読み込みました。") # 起動時のログとしては少し冗長なのでコメントアウト

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
    if before.archived and not after.archived: 
        return
    if not before.archived and after.archived: 
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
    
    load_data() 

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
    await client.wait_until_ready() 
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
            else: 
                await asyncio.sleep(20) 

        except asyncio.CancelledError:
            # print("プレゼンス更新タスクがキャンセルされました。") # 通常終了時は不要
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
            seconds_until_midnight += 24 * 60 * 60 

        await asyncio.sleep(max(1, seconds_until_midnight)) 
        
        first_new_year_message_sent_today = False
        akeome_records.clear() 
        print(f"[{datetime.now(timezone(timedelta(hours=9))):%Y-%m-%d %H:%M:%S}] 毎日のフラグと「あけおめ」記録をリセットしました。")
        save_data() 

async def reset_yearly_records_on_anniversary():
    global start_date, first_akeome_winners
    await client.wait_until_ready()
    while not client.is_closed():
        if not start_date:
            await asyncio.sleep(3600) 
            continue
        
        now_jst_for_calc = datetime.now(timezone(timedelta(hours=9)))

        try:
            current_year_anniversary_jst = datetime(now_jst_for_calc.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=timezone(timedelta(hours=9)))
        except ValueError: 
            print(f"[年間リセット] 開始日 {start_date.month}/{start_date.day} は今年({now_jst_for_calc.year}年)に存在しません。")
            await asyncio.sleep(24 * 3600) 
            continue

        next_reset_anniversary_jst = current_year_anniversary_jst
        if now_jst_for_calc >= current_year_anniversary_jst:
            try:
                next_reset_anniversary_jst = current_year_anniversary_jst.replace(year=current_year_anniversary_jst.year + 1)
            except ValueError: 
                 next_reset_anniversary_jst = current_year_anniversary_jst.replace(year=current_year_anniversary_jst.year + 1, day=28) # 閏年の2/29の翌年対策

        wait_seconds = (next_reset_anniversary_jst - now_jst_for_calc).total_seconds()
        
        if wait_seconds > 0 : # 未来の場合のみ待機
            # print(f"[年間リセット] 次回リセット予定: {next_reset_anniversary_jst.isoformat()} (JST) (残り約 {wait_seconds/3600:.2f} 時間)")
            await asyncio.sleep(wait_seconds)
        # else: 待機時間が0以下の場合は即時実行

        print(f"[{datetime.now(timezone(timedelta(hours=9))):%Y-%m-%d %H:%M:%S}] 年間リセットタイミングです。一番乗り記録を処理します。")
        
        if last_akeome_channel_id and first_akeome_winners: 
            target_channel = client.get_channel(last_akeome_channel_id)
            if target_channel and isinstance(target_channel, discord.TextChannel):
                # ランキング通知のロジック
                yearly_winner_counts = {}
                for yearly_winner_id_str in first_akeome_winners.values(): 
                    yearly_winner_counts[yearly_winner_id_str] = yearly_winner_counts.get(yearly_winner_id_str, 0) + 1
                
                yearly_sorted_counts = sorted(yearly_winner_counts.items(), key=lambda item: item[1], reverse=True)

                def get_yearly_winner_name(uid_str, guild_ctx): 
                    try:
                        member_obj = guild_ctx.get_member(int(uid_str))
                        return member_obj.display_name if member_obj else f"(ID: {uid_str})"
                    except ValueError:
                        return f"(不明なID: {uid_str})"

                yearly_ranking_lines = [
                    f"{idx+1}. {get_yearly_winner_name(uid, target_channel.guild)} 🏆 {count} 回"
                    for idx, (uid, count) in enumerate(yearly_sorted_counts[:10])
                ]
                
                yearly_end_date_footer = next_reset_anniversary_jst.date() - timedelta(days=1)
                yearly_footer_text = f"{start_date.strftime('%Y年%m月%d日')}から{yearly_end_date_footer.strftime('%Y年%m月%d日')}まで"
                
                yearly_embed = discord.Embed(title="🏅 一番乗り回数ランキング（年間リセット前）", description="\n".join(yearly_ranking_lines) if yearly_ranking_lines else "該当者なし", color=0xc0c0c0)
                yearly_embed.set_footer(text=yearly_footer_text)
                
                try:
                    await target_channel.send(embed=yearly_embed)
                except discord.Forbidden:
                    print(f"年間リセットランキングの送信権限がチャンネル ID {last_akeome_channel_id} にありません。")
                except Exception as e_send_yearly:
                    print(f"年間リセットランキングの送信中にエラー: {e_send_yearly}")

        first_akeome_winners.clear()
        new_start_date = next_reset_anniversary_jst.date() 
        print(f"[年間リセット] 一番乗り記録をクリアしました。新しい開始日: {new_start_date.isoformat()}")
        start_date = new_start_date 
        save_data() 

# ---------- メッセージ処理 ----------
@client.event
async def on_message(message: discord.Message):
    global first_new_year_message_sent_today, last_akeome_channel_id, akeome_records, akeome_history, start_date

    if message.author == client.user or message.author.bot: 
        return
    
    if not message.guild: 
        return
    
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    current_date_str = now_jst.date().isoformat()

    # --- 投票メッセージからのスレッド作成 ---
    if isinstance(message.channel, discord.TextChannel) and message.poll:
        can_create_threads_poll = await check_bot_permission(message.guild, message.channel, "create_public_threads")
        if can_create_threads_poll:
            poll_question_text = "投票スレッド" 
            if hasattr(message.poll, 'question'):
                if isinstance(message.poll.question, str):
                    poll_question_text = message.poll.question
                elif hasattr(message.poll.question, 'text') and isinstance(message.poll.question.text, str):
                     poll_question_text = message.poll.question.text
            
            thread_name = poll_question_text[:100].strip()
            fullwidth_space_match = re.search(r'　', thread_name) 
            if fullwidth_space_match:
                thread_name = thread_name[:fullwidth_space_match.start()].strip()
            thread_name = thread_name if thread_name else "投票に関するスレッド" 

            try:
                thread = await message.create_thread(name=thread_name, auto_archive_duration=10080) 
                print(f"投票メッセージからスレッドを作成: '{thread.name}' (チャンネル: {message.channel.name})")
                
                can_add_reactions_poll = await check_bot_permission(message.guild, message.channel, "add_reactions")
                if can_add_reactions_poll:
                    await message.add_reaction("✅")
            except Exception as e:
                print(f"投票スレッド作成/リアクション中にエラー: {e} (チャンネル: {message.channel.name})")
    
    # --- 通常メッセージからのスレッド作成 (条件付き、文字数・URLチェックなし) ---
    elif isinstance(message.channel, discord.TextChannel) and \
         message.type == discord.MessageType.default and \
         message.content: 
        
        if message.channel.id in AUTO_THREAD_EXCLUDED_CHANNELS:
            return

        content_stripped = message.content.strip()
        
        if content_stripped.startswith(BOT_COMMAND_PREFIXES):
            return

        can_create_threads_normal = await check_bot_permission(message.guild, message.channel, "create_public_threads")
        if not can_create_threads_normal:
            return # ボット固有の明示的な許可がなければ作成しない

        thread_name_normal = content_stripped[:80].strip() 
        thread_name_normal = re.sub(r'[\\/*?"<>|:]', '', thread_name_normal) 
        thread_name_normal = thread_name_normal if thread_name_normal else "関連スレッド"

        try:
            thread = await message.create_thread(name=thread_name_normal, auto_archive_duration=10080)
            print(f"通常メッセージ「{content_stripped[:30]}...」からスレッドを作成: '{thread.name}' (チャンネル: {message.channel.name})")

            can_add_reactions_normal = await check_bot_permission(message.guild, message.channel, "add_reactions")
            if can_add_reactions_normal:
                await message.add_reaction("💬") 
        except discord.errors.HTTPException as e:
            if e.status == 400 and hasattr(e, 'code') and e.code == 50035 : 
                 print(f"通常スレッド作成失敗(400/50035): スレッド名「{thread_name_normal}」が無効の可能性。詳細: {e.text if hasattr(e, 'text') else e}")
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
                if can_send_messages_akeome: # ボット固有の明示的な許可がある場合のみ送信
                    try:
                        await message.channel.send(f"{message.author.mention} が一番乗り！あけましておめでとう！")
                    except Exception as e_send:
                         print(f"一番乗りメッセージ送信中にエラー: {e_send}。チャンネル: '{message.channel.name}'")
                
                first_new_year_message_sent_today = True
                first_akeome_winners[current_date_str] = author_id_str
                
                if start_date is None: 
                    start_date = now_jst.date() 
                    print(f"初回の「あけおめ」記録。年間リセットの基準日を {start_date.isoformat()} に設定しました。")
            save_data() 

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
                # スレッド作成をリアクションで行いたい場合は、ここに専用ロジックを記述
                # 例:
                # if await check_bot_permission(guild, channel, "create_public_threads"):
                #     thread_name_react = message.content[:80].strip() or "リアクションからのスレッド"
                #     await message.create_thread(name=thread_name_react)
                #     print(f"✅リアクションからスレッド作成: {thread_name_react}")
                # else:
                #     print(f"✅リアクションがありましたが、スレッド作成権限がありません。")

                # 現在は on_message を呼ばない設定
                # await on_message(message) 
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
                for i, (uid_cmd, ts_cmd) in enumerate(sorted_today): # 変数名変更
                    if uid_cmd == user_id_str_cmd:
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
                    # 有効な日付キーのみを対象とする
                    valid_date_keys = [d for d in first_akeome_winners.keys() if isinstance(d, str) and re.match(r'^\d{4}-\d{2}-\d{2}$', d)]
                    if valid_date_keys:
                        last_win_date_str = max(valid_date_keys)
                        last_win_date = datetime.fromisoformat(last_win_date_str).date()
                        embed.set_footer(text=f"集計期間: {start_date.strftime('%Y/%m/%d')} ～ {last_win_date.strftime('%Y/%m/%d')}")
                except Exception as e_footer: 
                     print(f"過去ランキングのフッター生成エラー: {e_footer}")
                     # エラー時もデフォルトフッター (上で設定済み) が使われる

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
