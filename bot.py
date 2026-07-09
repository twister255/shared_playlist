import os
import aiohttp
import asyncio
import sqlite3
import re
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ===== СОСТОЯНИЯ =====
class SongState(StatesGroup):
    choosing_method = State()
    waiting_for_link = State()
    waiting_for_title = State()
    waiting_for_delete_id = State()
    waiting_for_search_query = State()

# ===== БАЗА ДАННЫХ =====
def init_db():
    conn = sqlite3.connect('playlist.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist TEXT,
            title TEXT,
            url TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_song_to_db(artist, title, url):
    conn = sqlite3.connect('playlist.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO songs (artist, title, url) VALUES (?, ?, ?)',
        (artist, title, url)
    )
    conn.commit()
    conn.close()

def get_all_songs():
    conn = sqlite3.connect('playlist.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, artist, title, url FROM songs')
    songs = cursor.fetchall()
    conn.close()
    return songs

def delete_song_from_db(song_id):
    conn = sqlite3.connect('playlist.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM songs WHERE id = ?', (song_id,))
    conn.commit()
    conn.close()

# ===== КЛАВИАТУРЫ =====
def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=" Плейлист")],
            [KeyboardButton(text="➕ Добавить песню"), KeyboardButton(text=" Удалить песню")],
            [KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_cancel_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Назад")]],
        resize_keyboard=True
    )
    return keyboard

def get_add_method_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Поиск"), KeyboardButton(text="✍️ Ручной ввод")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_search_results_keyboard(results):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for i, track in enumerate(results, 1):
        button_text = f"{i}. {track['artist']} - {track['title']}"
        if len(button_text) > 50:
            button_text = button_text[:47] + "..."
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=button_text, callback_data=f"select_{i}")
        ])
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
    ])
    return keyboard

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def shorten_url(url):
    if len(url) > 40:
        return url[:40] + "..."
    return url

def is_music_link(text):
    music_patterns = [
        r'vk\.com', r'vk\.ru', r'm\.vk\.com', r'm\.vk\.ru',
        r'music\.yandex', r'youtube\.com', r'youtu\.be',
        r'spotify\.com', r'deezer\.com', r'music\.apple\.com'
    ]
    for pattern in music_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

async def search_deezer(query):
    try:
        async with aiohttp.ClientSession() as session:
            params = {'q': query, 'limit': 5}
            async with session.get(
                'https://api.deezer.com/search',
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get('data', [])
                    if results:
                        return [
                            {
                                'artist': track.get('artist', {}).get('name', 'Неизвестный'),
                                'title': track.get('title', 'Неизвестно'),
                                'url': track.get('link', '')
                            }
                            for track in results
                        ]
        return []
    except Exception as e:
        print(f"Ошибка поиска Deezer: {e}")
        return []

user_temp_data = {}

# ===== CALLBACK ОБРАБОТЧИКИ =====

@dp.callback_query(F.data.startswith('select_'))
async def select_track(callback: types.CallbackQuery, state: FSMContext):
    track_number = int(callback.data.split('_')[1])
    
    temp_data = user_temp_data.get(callback.from_user.id, {})
    results = temp_data.get('search_results', [])
    
    if 1 <= track_number <= len(results):
        track = results[track_number - 1]
        
        add_song_to_db(track['artist'], track['title'], '')
        
        if callback.from_user.id in user_temp_data:
            del user_temp_data[callback.from_user.id]
        await state.clear()
        
        # Сначала подтверждаем callback (убирает "часики" на кнопке)
        await callback.answer()
        
        # Удаляем сообщение с inline-кнопками
        await callback.message.delete()
        
        # Отправляем новое сообщение с результатом и главным меню
        await callback.message.answer(
            f"✅ <b>Песня добавлена!</b>\n\n <b>{track['artist']} - {track['title']}</b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
    else:
        await callback.answer("❌ Неверный номер", show_alert=True)

@dp.callback_query(F.data == 'cancel')
async def cancel_search(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id in user_temp_data:
        del user_temp_data[callback.from_user.id]
    await state.clear()
    
    # Подтверждаем callback
    await callback.answer()
    
    # Удаляем сообщение с кнопками
    await callback.message.delete()
    
    # Отправляем новое сообщение
    await callback.message.answer(
        "❌ Поиск отменён",
        reply_markup=get_main_keyboard()
    )

# ===== ГЛАВНЫЕ КНОПКИ МЕНЮ =====

@dp.message(lambda msg: msg.text and "Плейлист" in msg.text)
async def show_playlist_button(message: types.Message, state: FSMContext):
    await state.clear()
    songs = get_all_songs()
    
    if not songs:
        await message.answer("🎵 <b>Плейлист пуст!</b>\n\nНажми ➕ Добавить песню, чтобы добавить трек!", reply_markup=get_main_keyboard(), parse_mode="HTML")
        return
    
    playlist_text = "🎧 <b>ПЛЕЙЛИСТ</b> 🎧\n\n"
    for i, (song_id, artist, title, url) in enumerate(songs, 1):
        playlist_text += f"{i}. <b>{artist} - {title}</b>\n"
        if url and 'deezer.com' not in url:
            playlist_text += f"🔗 {shorten_url(url)}\n"
        playlist_text += "\n"
    
    await message.answer(playlist_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@dp.message(lambda msg: msg.text and "Помощь" in msg.text)
async def help_button(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📚 <b>Как пользоваться:</b>\n\n"
        "<b>➕ Добавить песню:</b>\n"
        "Выбери один из способов:\n"
        "• 🔍 <b>Поиск</b> — напиши название, бот найдёт сам\n"
        "• ✍️ <b>Ручной ввод</b> — отправь ссылку и название\n\n"
        "<b>🎵 Плейлист:</b>\n"
        "• Показать все добавленные песни\n\n"
        "<b>🗑 Удалить песню:</b>\n"
        "• Напиши номер песни из плейлиста, чтобы удалить её\n\n"
        "<b>🔙 Назад:</b>\n"
        "• Отменить текущее действие",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

@dp.message(lambda msg: msg.text and "Добавить песню" in msg.text)
async def start_add_song(message: types.Message, state: FSMContext):
    await state.set_state(SongState.choosing_method)
    await message.answer(
        " <b>Выбери способ добавления:</b>\n\n"
        "🔍 <b>Поиск</b> — напиши название песни, бот найдёт её автоматически\n\n"
        "✍️ <b>Ручной ввод</b> — отправь ссылку и введи название вручную\n\n",
        reply_markup=get_add_method_keyboard(),
        parse_mode="HTML"
    )

# ===== ОБРАБОТЧИК ВЫБОРА СПОСОБА =====

@dp.message(SongState.choosing_method)
async def process_method_choice(message: types.Message, state: FSMContext):
    text = message.text or ""
    
    if "Назад" in text:
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    
    if "Поиск" in text:
        await state.set_state(SongState.waiting_for_search_query)
        await message.answer(
            "🔍 <b>Поиск песни</b>\n\nНапиши название или исполнителя:\n<i>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return
    
    if "Ручной" in text:
        await state.set_state(SongState.waiting_for_link)
        await message.answer(
            "📎 <b>Ручной ввод</b>\n\nОтправь ссылку на песню:\n• ВКонтакте (vk.com, vk.ru)\n• Яндекс.Музыка (music.yandex.ru)\n• YouTube (youtube.com)\n• Spotify, Deezer, Apple Music\n\n",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return
    
    await message.answer("❓ Не понимаю выбор. Используй кнопки:", reply_markup=get_add_method_keyboard())

# ===== ПОИСК ЧЕРЕЗ DEEZER =====

@dp.message(SongState.waiting_for_search_query)
async def process_search_query(message: types.Message, state: FSMContext):
    text = message.text or ""
    if "Назад" in text:
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    
    await message.answer(f"🔍 Ищу <b>{text}</b>... Подожди секунду.")
    results = await search_deezer(text)
    
    if results:
        user_temp_data[message.from_user.id] = {'search_results': results}
        results_text = f"🎵 <b>Нашёл {len(results)} песен:</b>\n\nВыбери нужную:"
        keyboard = get_search_results_keyboard(results)
        await message.answer(results_text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message.answer("❌ Ничего не найдено. Попробуй написать по-другому.", reply_markup=get_cancel_keyboard())

# ===== РУЧНОЙ ВВОД =====

@dp.message(SongState.waiting_for_link)
async def process_link(message: types.Message, state: FSMContext):
    text = message.text or ""
    if "Назад" in text:
        await state.clear()
        if message.from_user.id in user_temp_data: del user_temp_data[message.from_user.id]
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    
    if not is_music_link(text):
        await message.answer("❌ Это не ссылка! Отправь ссылку из ВК, Яндекс, YouTube...", reply_markup=get_cancel_keyboard())
        return
    
    user_temp_data[message.from_user.id] = {'url': text}
    await state.set_state(SongState.waiting_for_title)
    await message.answer("✅ Ссылка принята!\n\nТеперь напиши <b>название</b>:\n<i>Исполнитель - Название</i>", reply_markup=get_cancel_keyboard(), parse_mode="HTML")

@dp.message(SongState.waiting_for_title)
async def process_title(message: types.Message, state: FSMContext):
    text = message.text or ""
    if "Назад" in text:
        await state.clear()
        if message.from_user.id in user_temp_data: del user_temp_data[message.from_user.id]
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    
    if " - " not in text:
        await message.answer("❌ Неверный формат! Используй: <b>Исполнитель - Название</b>", reply_markup=get_cancel_keyboard(), parse_mode="HTML")
        return
    
    parts = text.split(" - ", 1)
    artist, title = parts[0].strip(), parts[1].strip()
    url = user_temp_data.get(message.from_user.id, {}).get('url', '')
    
    add_song_to_db(artist, title, url)
    if message.from_user.id in user_temp_data: del user_temp_data[message.from_user.id]
    await state.clear()
    
    await message.answer(f"✅ <b>Песня добавлена!</b>\n\n🎵 <b>{artist} - {title}</b>", reply_markup=get_main_keyboard(), parse_mode="HTML")

# ===== УДАЛЕНИЕ ПЕСНИ =====

@dp.message(lambda msg: msg.text and "Удалить" in msg.text)
async def start_delete_song(message: types.Message, state: FSMContext):
    await state.clear()
    songs = get_all_songs()
    if not songs:
        await message.answer("🎵 Плейлист пуст!", reply_markup=get_main_keyboard())
        return
    
    playlist_text = "🎧 <b>ПЛЕЙЛИСТ</b> 🎧\n\n"
    for i, (song_id, artist, title, url) in enumerate(songs, 1):
        playlist_text += f"{i}. <b>{artist} - {title}</b>\n"
        if url and 'deezer.com' not in url:
            playlist_text += f"   🔗 {shorten_url(url)}\n"
        playlist_text += "\n"
    playlist_text += "Напиши <b>номер песни</b> для удаления:"
    
    await state.set_state(SongState.waiting_for_delete_id)
    await message.answer(playlist_text, reply_markup=get_cancel_keyboard(), parse_mode="HTML")

@dp.message(SongState.waiting_for_delete_id)
async def process_delete(message: types.Message, state: FSMContext):
    if "Назад" in (message.text or ""):
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=get_main_keyboard())
        return
    
    try:
        list_number = int(message.text)
        songs = get_all_songs()
        if list_number < 1 or list_number > len(songs):
            await message.answer(f"❌ Нет песни с номером {list_number}!", reply_markup=get_cancel_keyboard())
            return
        
        delete_song_from_db(songs[list_number - 1][0])
        await state.clear()
        await message.answer(f"🗑 Песня #{list_number} удалена!", reply_markup=get_main_keyboard())
    except ValueError:
        await message.answer("❌ Напиши номер песни (число)!", reply_markup=get_cancel_keyboard())

# ===== ГЛОБАЛЬНАЯ КНОПКА НАЗАД =====

@dp.message(lambda msg: msg.text and msg.text == "🔙 Назад")
async def cancel_action(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id in user_temp_data: del user_temp_data[message.from_user.id]
    await message.answer("❌ Действие отменено", reply_markup=get_main_keyboard())

# ===== СТАРТ И ЭКСПОРТ =====

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id in user_temp_data: del user_temp_data[message.from_user.id]
    await message.answer(
        "🎉 <b>Привет! Я бот для создания общего плейлиста!</b>\n\n"
        "🎧 <b>Что я умею:</b>\n"
        "• Искать песни по названию или исполнителю\n"
        "• Добавлять песни по ссылке\n"
        "• Показывать общий плейлист\n"
        "• Удалять песни из плейлиста\n\n"
        "👇 <b>Используй кнопки ниже:</b>",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

@dp.message(Command("export"))
async def cmd_export(message: types.Message, state: FSMContext):
    await state.clear()
    songs = get_all_songs()
    if not songs:
        await message.answer("🎵 Плейлист пуст!", reply_markup=get_main_keyboard())
        return
    
    csv_content = "Artist,Title\n"
    txt_content = ""
    full_content = "🎧 ПЛЕЙЛИСТ\n" + "="*50 + "\n\n"
    
    for song_id, artist, title, url in songs:
        csv_content += f"{artist.replace(',', ' ')},{title.replace(',', ' ')}\n"
        txt_content += f"{artist} - {title}\n"
        full_content += f"{artist} - {title}\n"
        if url and 'deezer.com' not in url:
            full_content += f"   {url}\n"
        full_content += "\n"
    
    await message.answer(f" <b>Экспорт плейлиста!</b>\n\nВсего песен: <b>{len(songs)}</b>", reply_markup=get_main_keyboard(), parse_mode="HTML")
    
    await message.answer_document(document=types.BufferedInputFile(file=csv_content.encode('utf-8-sig'), filename="playlist_yandex.csv"), caption="📊 CSV для Яндекс.Музыки")
    await message.answer_document(document=types.BufferedInputFile(file=txt_content.encode('utf-8'), filename="playlist.txt"), caption="📝 Простой список")
    await message.answer_document(document=types.BufferedInputFile(file=full_content.encode('utf-8'), filename="playlist_full.txt"), caption="📋 Полный список")

# ===== ЗАПУСК =====
async def main():
    print("🎵 Бот запущен!")
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 Бот остановлен.")
