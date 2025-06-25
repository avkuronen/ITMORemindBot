#!/usr/bin/env python3
import sqlite3
from os import environ
from datetime import datetime
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dataclasses import dataclass
import re

DB_NAME = "tasks.db"

@dataclass
class Task:
    id: int
    title: str
    due_datetime: datetime
    done: bool = False
    note: str = ""

class TaskStorage:
    def __init__(self, db_name=DB_NAME):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()

    def _table_name(self, user_id: int) -> str:
        return f'USER_{user_id}'

    def ensure_user_table(self, user_id: int):
        table = self._table_name(user_id)
        self.cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_datetime TEXT NOT NULL,
                done INTEGER DEFAULT 0,
                note TEXT
            )
        """)
        self.conn.commit()

    def add_task(self, user_id: int, title: str, due_datetime: str):
        print('[LOG] Task add')
        self.ensure_user_table(user_id)
        table = self._table_name(user_id)
        self.cursor.execute(
            f"INSERT INTO {table} (title, due_datetime) VALUES (?, ?)",
            (title, due_datetime)
        )
        self.conn.commit()

    def list_tasks(self, user_id: int):
        print(f'[LOG] Get tasks of {user_id}')
        table = self._table_name(user_id)
        self.ensure_user_table(user_id)
        self.cursor.execute(f"SELECT id, title, due_datetime, done FROM {table}")
        return self.cursor.fetchall()

    def mark_done(self, user_id: int, task_id: int, done=True):
        print(f'[LOG] Done {task_id} by {user_id}')
        table = self._table_name(user_id)
        self.cursor.execute(f"UPDATE {table} SET done = ? WHERE id = ?", (int(done), task_id))
        self.conn.commit()

    def delete_task(self, user_id: int, task_id: int):
        print(f'[LOG] Delete {task_id} by {user_id}')
        table = self._table_name(user_id)
        self.cursor.execute(f"DELETE FROM {table} WHERE id = ?", (task_id,))
        self.conn.commit()
        self.cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = self.cursor.fetchone()[0]
        if count == 0:
            self.cursor.execute(f"DROP TABLE {table}")
            self.conn.commit()

    def get_all_user_ids(self):
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = self.cursor.fetchall()
        user_ids = []
        for (table_name,) in tables:
            match = re.match(r"USER_(\d+)", table_name)
            if match:
                user_ids.append(int(match.group(1)))
        return user_ids

    def get_pending_tasks(self, user_id: int):
        table = self._table_name(user_id)
        self.ensure_user_table(user_id)
        self.cursor.execute(f"SELECT id, title, due_datetime FROM {table} WHERE done = 0")
        return self.cursor.fetchall()

    def close(self):
        self.conn.close()

storage = TaskStorage()

async def new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) < 3:
        await update.message.reply_text("Используйте: /new <ДД.ММ.ГГГГ ЧЧ:ММ> <название задания>")
        return
    try:
        due_str = context.args[0] + ' ' + context.args[1]
        due = datetime.strptime(due_str, "%d.%m.%Y %H:%M")
        title = ' '.join(context.args[2:])
    except ValueError:
        await update.message.reply_text("Неверный формат даты. Используйте ДД.ММ.ГГГГ ЧЧ:ММ")
        return
    storage.add_task(user_id, title, due.isoformat())
    await update.message.reply_text(f"Задание '{title}' добавлено!")

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = storage.list_tasks(user_id)
    if not rows:
        await update.message.reply_text("У вас нет заданий.")
        return
    msg = "Ваши задания:\n" + '\n'.join(map(lambda task: f"{task[0]}. {task[1]} — {task[2]} " + ("✅" if task[3] else "❌"), rows))
    await update.message.reply_text(msg)

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Используйте: /done <id>")
        return
    storage.mark_done(user_id, int(context.args[0]), True)
    await update.message.reply_text("Задание отмечено как выполненное!")

async def undone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Используйте: /undone <id>")
        return
    storage.mark_done(user_id, int(context.args[0]), False)
    await update.message.reply_text("Задание снова активное.")

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Используйте: /delete <id>")
        return
    storage.delete_task(user_id, int(context.args[0]))
    await update.message.reply_text("Задание удалено.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот остановлен. До встречи!")
    storage.close()
    await context.application.stop()

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Команды:\n/done <Номер задания>, /undone <Номер задания> - Пометить задание сделанным/несделанным\n' + \
            "/help - Показать это сообщение\n/new <ДД:ММ:ГГГГ ЧЧ:мм> <Описание задания>\n" + \
            "/delete <Номер задания> - удалить задание\n/tasks - показать список заданий\n/stop - остановить бота (для разработчиков)")

bot = Bot(token=environ['TGBOTTOKEN'])

async def reminder_task(context: ContextTypes.DEFAULT_TYPE):
    print("[LOG] Reminder job is running...")
    local_storage = TaskStorage()
    user_ids = local_storage.get_all_user_ids()
    for user_id in user_ids:
        tasks = local_storage.get_pending_tasks(user_id)
        if tasks:
            message = "Напоминание! У вас есть невыполненные задачи:\n" + '\n'.join(map(lambda t: f"{t[0]}. {t[1]} — {t[2]}\n", tasks))
            try:
                await app.bot.send_message(chat_id=user_id, text=message)
            except Exception as e:
                print(f"[ERROR] Не удалось отправить сообщение {user_id}: {e}")
    local_storage.close()


app = ApplicationBuilder().token(environ['TGBOTTOKEN']).build()
app.add_handler(CommandHandler("new", new))
app.add_handler(CommandHandler("tasks", tasks))
app.add_handler(CommandHandler("done", done))
app.add_handler(CommandHandler("undone", undone))
app.add_handler(CommandHandler("delete", delete))
app.add_handler(CommandHandler("stop", stop))
app.add_handler(CommandHandler("help", help))
app.job_queue.run_repeating(reminder_task, interval=6 * 60 * 60, first=10)
app.run_polling()
