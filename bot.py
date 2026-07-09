import os
import aiohttp
import asyncio
import sqlite3
import re
import io
from aiogram import Bot, Dispatcher, types
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
            url TEXT,
            artwork TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_song_to_db(artist, title, url, artwork=''):
    conn = sqlite3.connect('playlist.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO songs (artist, title, url, artwork) VALUES (?, ?, ?, ?)',
        (artist, title, url, artwork)
    )
    conn.commit()
    conn.close()

def get_all_songs():
    conn = sqlite3.connect('playlist.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, artist, title, url, artwork FROM songs')
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
            [KeyboardButton(text="🎵 Плейлист")],
            [KeyboardButton(text="➕ Добавить песню"), KeyboardButton(text="🗑 Удалить песню")],
            [KeyboardButton(text=" Помощь")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_cancel_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_add_method_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Поиск в iTunes"), KeyboardButton(text="✍️ Ручной ввод")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_search_results_keyboard(results):
    """Создаёт inline-кнопки со списком найденных песен"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for i, track in enumerate(results):
        # Обрезаем длинные названия
        button_text = f"🎵 {track['artist']} - {track['title']}"
        if len(button_text) > 50:
            button_text = button_text[:47] + "..."
        
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"select_track_{i}"
            )
        ])
    
    # Кнопка отмены
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_search")
    ])
    
    return keyboard

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def shorten_url(url):
    if len(url) > 40:
        return url[:40] + "..."
    return url

def is_music_link(text):
    music_patterns = [
        r'vk\.com',
        r'vk\.ru',
        r'm\.vk\.com',
        r'm\.vk\.ru',
        r'music\.yandex',
        r'youtube\.com',
        r'youtu\.be',
        r'spotify\.com',
        r'deezer\.com',
        r'music\.apple\.com',
        r'itunes\.apple\.com'
    ]
    for pattern in music_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

async def search_deezer(query):
    """Ищет песню в Deezer"""
    try:
        async with aiohttp.ClientSession() as session:
            params = {
                'q': query,
                'limit': 5
            }
            
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
                                'url': track.get('link', ''),
                                'preview': track.get('preview', ''),
                                'artwork': track.get('album', {}).get('cover_big', '')
                            }
                            for track in results
                        ]
        return []
    except Exception as e:
        print(f"Ошибка поиска : {e}")
        return []

# ===== ХРАНИЛИЩЕ ВРЕМЕННЫХ ДАННЫХ =====
user_temp_data = {}

# ===== ОБРАБОТЧИКИ =====
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id in user_temp_data:
        del user_temp_data[message.from_user.id]
    
    await message.answer(
        "🎉 <b>Привет! Я бот для создания общего плейлиста!</b>\n\n"
        "🎧 <b>Что я умею:</b>\n"
        "• Искать песни по названию или исполнителю\n"
        "• Добавлять песни по ссылке\n"
        "• Показывать общий плейлист с обложками\n"
        "• Удалять песни из плейлиста\n\n"
        "👇 <b>Используй кнопки ниже:</b>",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

@dp.message(lambda msg: msg.text == " Плейлист")
async def show_playlist_button(message: types.Message, state: FSMContext):
    await state.clear()
    
    songs = get_all_songs()
    
    if not songs:
        await message.answer(
            "🎵 <b>Плейлист пуст!</b>\n\n"
            "Нажми ➕ Добавить песню, чтобы добавить трек!",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
        return
    
    playlist_text = "🎧 <b>ПЛЕЙЛИСТ</b> 🎧\n\n"
    
    for i, (song_id, artist, title, url, artwork) in enumerate(songs, 1):
        playlist_text += f"{i}. <b>{artist} - {title}</b>\n"
        if url:
            playlist_text += f"🔗 {shorten_url(url)}\n"
        playlist_text += "\n"
    
    await message.answer(
        playlist_text,
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

@dp.message(lambda msg: msg.text == "❓ Помощь")
async def help_button(message: types.Message, state: FSMContext):
    await state.clear()
    
    await message.answer(
        "📚 <b>Как пользоваться:</b>\n\n"
        "<b>➕ Добавить песню:</b>\n"
        "Выбери один из способов:\n"
        "• 🔍 <b>Поиск в iTunes</b> — напиши название, бот найдёт сам\n"
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

@dp.message(lambda msg: msg.text == "➕ Добавить песню")
async def start_add_song(message: types.Message, state: FSMContext):
    await state.set_state(SongState.choosing_method)
    
    await message.answer(
        "📎 <b>Выбери способ добавления:</b>\n\n"
        "🔍 <b>Поиск в iTunes</b> — напиши название песни, бот найдёт её автоматически\n\n"
        "✍️ <b>Ручной ввод</b> — отправь ссылку и введи название вручную\n\n",
        reply_markup=get_add_method_keyboard(),
        parse_mode="HTML"
    )

@dp.message(SongState.choosing_method)
async def process_method_choice(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer(
            "❌ Добавление отменено",
            reply_markup=get_main_keyboard()
        )
        return
    
    if message.text == " Поиск":
        await state.set_state(SongState.waiting_for_search_query)
        await message.answer(
            "🔍 <b>Поиск песни</b>\n\n"
            "Напиши название песни или исполнителя:\n",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return
    
    if message.text == "✍️ Ручной ввод":
        await state.set_state(SongState.waiting_for_link)
        await message.answer(
            "📎 <b>Ручной ввод</b>\n\n"
            "Отправь ссылку на песню:\n"
            "• ВКонтакте (vk.com, vk.ru)\n"
            "• Яндекс.Музыка (music.yandex.ru)\n"
            "• YouTube (youtube.com)\n"
            "• Spotify, Deezer, Apple Music\n\n",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return
    
    await message.answer(
        "❓ Не понимаю выбор. Используй кнопки ниже:",
        reply_markup=get_add_method_keyboard()
    )

@dp.message(SongState.waiting_for_search_query)
async def process_search_query(message: types.Message, state: FSMContext):
    if message.text == " Назад":
        await state.clear()
        await message.answer(
            "❌ Добавление отменено",
            reply_markup=get_main_keyboard()
        )
        return
    
    await message.answer(f"🔍 Ищу <b>{message.text}</b>... Подожди секунду.")
    
    results = await search_deezer(message.text)
    
    if results:
        user_temp_data[message.from_user.id] = {'search_results': results}
        
        results_text = f"🎵 <b>Нашёл {len(results)} песен:</b>\n\nВыбери нужную:"
        
        keyboard = get_search_results_keyboard(results)
        
        await message.answer(
            results_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "❌ Ничего не найдено.\n\n"
            "Попробуй:\n"
            "• Написать по-другому\n"
            "• Выбрать ✍️ Ручной ввод\n\n",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )

# ===== INLINE КНОПКИ ВЫБОРА ПЕСНИ =====
@dp.callback_query(lambda c: c.data.startswith('select_track_'))
async def select_track(callback: types.CallbackQuery, state: FSMContext):
    track_index = int(callback.data.split('_')[2])
    
    temp_data = user_temp_data.get(callback.from_user.id, {})
    results = temp_data.get('search_results', [])
    
    if 0 <= track_index < len(results):
        track = results[track_index]
        
        add_song_to_db(
            track['artist'],
            track['title'],
            track['url'],
            track.get('artwork', '')
        )
        
        if callback.from_user.id in user_temp_data:
            del user_temp_data[callback.from_user.id]
        
        await state.clear()
        
        await callback.message.edit_text(
            f"✅ <b>Песня добавлена!</b>\n\n"
            f"🎵 <b>{track['artist']} - {track['title']}</b>\n"
            f"🔗 {shorten_url(track['url'])}",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == 'cancel_search')
async def cancel_search(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id in user_temp_data:
        del user_temp_data[callback.from_user.id]
    
    await state.clear()
    
    await callback.message.edit_text(
        "❌ Поиск отменён",
        reply_markup=get_main_keyboard()
    )
    
    await callback.answer()

# ===== РУЧНОЙ ВВОД =====
@dp.message(SongState.waiting_for_link)
async def process_link(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        if message.from_user.id in user_temp_data:
            del user_temp_data[message.from_user.id]
        await message.answer(
            "❌ Добавление отменено",
            reply_markup=get_main_keyboard()
        )
        return
    
    text = message.text
    
    if not is_music_link(text):
        await message.answer(
            "❌ Это не похоже на ссылку на музыку!\n\n"
            "Отправь ссылку из ВК, Яндекс.Музыки, YouTube и т.д.\n\n",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return
    
    user_temp_data[message.from_user.id] = {'url': text}
    
    await state.set_state(SongState.waiting_for_title)
    await message.answer(
        "✅ Ссылка принята!\n\n"
        "Теперь напиши <b>название песни</b> в формате:\n"
        "<i>Исполнитель - Название</i>\n\n",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@dp.message(SongState.waiting_for_title)
async def process_title(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        if message.from_user.id in user_temp_data:
            del user_temp_data[message.from_user.id]
        await message.answer(
            "❌ Добавление отменено",
            reply_markup=get_main_keyboard()
        )
        return
    
    text = message.text
    
    if " - " not in text:
        await message.answer(
            "❌ Неверный формат!\n\n"
            "Используй: <b>Исполнитель - Название</b>\n",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return
    
    parts = text.split(" - ", 1)
    artist = parts[0].strip()
    title = parts[1].strip()
    
    temp_data = user_temp_data.get(message.from_user.id, {})
    url = temp_data.get('url', '')
    
    add_song_to_db(artist, title, url, '')
    
    if message.from_user.id in user_temp_data:
        del user_temp_data[message.from_user.id]
    
    await state.clear()
    
    await message.answer(
        f"✅ <b>Песня добавлена!</b>\n\n"
        f"🎵 <b>{artist} - {title}</b>\n"
        f" {shorten_url(url) if url else 'Без ссылки'}",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

# ===== УДАЛЕНИЕ ПЕСНИ =====
@dp.message(lambda msg: msg.text == "🗑 Удалить песню")
async def start_delete_song(message: types.Message, state: FSMContext):
    await state.clear()
    
    songs = get_all_songs()
    
    if not songs:
        await message.answer(
            "🎵 Плейлист пуст! Нечего удалять.",
            reply_markup=get_main_keyboard()
        )
        return
    
    playlist_text = "🎧 <b>ПЛЕЙЛИСТ</b> 🎧\n\n"
    
    for i, (song_id, artist, title, url, artwork) in enumerate(songs, 1):
        playlist_text += f"{i}. <b>{artist} - {title}</b>\n"
        if url:
            playlist_text += f"   🔗 {shorten_url(url)}\n"
        playlist_text += "\n"
    
    playlist_text += "Напиши <b>номер песни</b>, которую хочешь удалить:\n\n"
    
    await state.set_state(SongState.waiting_for_delete_id)
    await message.answer(
        playlist_text,
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@dp.message(SongState.waiting_for_delete_id)
async def process_delete(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer(
            "❌ Удаление отменено",
            reply_markup=get_main_keyboard()
        )
        return
    
    try:
        list_number = int(message.text)
        songs = get_all_songs()
        
        if list_number < 1 or list_number > len(songs):
            await message.answer(
                f"❌ Нет песни с номером {list_number}!\n\n"
                f"В плейлисте всего {len(songs)} песен.\n\n",
                reply_markup=get_cancel_keyboard(),
                parse_mode="HTML"
            )
            return
        
        real_song_id = songs[list_number - 1][0]
        delete_song_from_db(real_song_id)
        
        await state.clear()
        await message.answer(
            f" Песня #{list_number} удалена!",
            reply_markup=get_main_keyboard()
        )
    except ValueError:
        await message.answer(
            "❌ Напиши номер песни (число)!\n\n",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )

@dp.message(lambda msg: msg.text == "🔙 Назад")
async def cancel_action(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id in user_temp_data:
        del user_temp_data[message.from_user.id]
    await message.answer(
        "❌ Действие отменено",
        reply_markup=get_main_keyboard()
    )

# ===== ЭКСПОРТ ПЛЕЙЛИСТА =====
@dp.message(Command("export"))
async def cmd_export(message: types.Message, state: FSMContext):
    await state.clear()
    
    songs = get_all_songs()
    
    if not songs:
        await message.answer(
            "🎵 Плейлист пуст! Нечего экспортировать.",
            reply_markup=get_main_keyboard()
        )
        return
    
    csv_content = "Artist,Title\n"
    for song_id, artist, title, url, artwork in songs:
        artist_clean = artist.replace(",", " ")
        title_clean = title.replace(",", " ")
        csv_content += f"{artist_clean},{title_clean}\n"
    
    csv_file = io.BytesIO(csv_content.encode('utf-8-sig'))
    csv_file.name = "playlist_for_yandex.csv"
    
    txt_content = ""
    for song_id, artist, title, url, artwork in songs:
        txt_content += f"{artist} - {title}\n"
    
    txt_file = io.BytesIO(txt_content.encode('utf-8'))
    txt_file.name = "playlist.txt"
    
    full_content = "🎧 ПЛЕЙЛИСТ\n"
    full_content += "=" * 50 + "\n\n"
    for i, (song_id, artist, title, url, artwork) in enumerate(songs, 1):
        full_content += f"{i}. {artist} - {title}\n"
        full_content += f"   {url}\n\n"
    
    full_file = io.BytesIO(full_content.encode('utf-8'))
    full_file.name = "playlist_full.txt"
    
    await message.answer(
        f"📤 <b>Экспорт плейлиста!</b>\n\n"
        f"🎵 Всего песен: <b>{len(songs)}</b>\n\n"
        f"📎 Отправляю 3 файла:\n"
        f"1️⃣ <b>playlist_for_yandex.csv</b> - для импорта в Яндекс.Музыку\n"
        f"2️⃣ <b>playlist.txt</b> - простой список\n"
        f"3️⃣ <b>playlist_full.txt</b> - полный список со ссылками\n\n"
        f"👇 <b>Инструкция по импорту в Яндекс.Музыку:</b>",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )
    
    await message.answer_document(
        document=types.BufferedInputFile(
            file=csv_file.getvalue(),
            filename=csv_file.name
        ),
        caption="📊 CSV файл для импорта в Яндекс.Музыку"
    )
    
    await message.answer_document(
        document=types.BufferedInputFile(
            file=txt_file.getvalue(),
            filename=txt_file.name
        ),
        caption=" Простой список песен"
    )
    
    await message.answer_document(
        document=types.BufferedInputFile(
            file=full_file.getvalue(),
            filename=full_file.name
        ),
        caption="📋 Полный список со ссылками"
    )
    
    await message.answer(
        "🎯 <b>Как импортировать в Яндекс.Музыку:</b>\n\n"
        "<b>Способ 1: TuneMyMusic (бесплатно, до 1000 треков)</b>\n"
        "1. Зайди на https://tunemymusic.com/ru/\n"
        "2. Нажми 'Начать'\n"
        "3. Выбери 'Файл' → загрузи <b>playlist_for_yandex.csv</b>\n"
        "4. Выбери 'Яндекс.Музыка' как целевой сервис\n"
        "5. Авторизуйся в Яндексе\n"
        "6. Нажми 'Перенести музыку'\n\n"
        "<b>Способ 2: Soundiiz (бесплатно, до 200 треков)</b>\n"
        "1. Зайди на https://soundiiz.com/\n"
        "2. Регистрация → 'Import from file'\n"
        "3. Загрузи <b>playlist_for_yandex.csv</b>\n"
        "4. Выбери Яндекс.Музыку\n\n"
        "<b>После импорта:</b>\n"
        "• Открой Яндекс.Музыку\n"
        "• Найди импортированный плейлист\n"
        "• Нажми 'Скачать' для офлайн прослушивания!\n\n"
        "⚠️ <b>Важно:</b> Не все песни могут найтись в Яндексе - "
        "сервис попытается найти похожие треки.",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

# ===== ЗАПУСК БОТА =====
async def main():
    print(" Бот с ручным вводом запущен!")
    print("🎧 Готов добавлять песни!")
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(" Бот остановлен.")
