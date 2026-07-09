import os
import aiohttp
import asyncio
import sqlite3
import re
import io
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


TOKEN = os.getenv("BOT_TOKEN")


bot = Bot(token=TOKEN)
dp = Dispatcher()

# ===== СОСТОЯНИЯ =====
class SongState(StatesGroup):
    waiting_for_link = State()
    waiting_for_title = State()
    waiting_for_delete_id = State()

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
            [KeyboardButton(text="🎵 Плейлист")],
            [KeyboardButton(text="➕ Добавить песню"), KeyboardButton(text="🗑 Удалить песню")],
            [KeyboardButton(text="❓ Помощь")]
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

# ===== ХРАНИЛИЩЕ ВРЕМЕННЫХ ДАННЫХ =====
user_temp_data = {}

# ===== ОБРАБОТЧИКИ =====
async def get_vk_track_info(url):
    """Получает информацию о треке из ВК"""
    # Токен ВК (замени на свой!)
    VK_TOKEN = vk1.a.ylsasimFIVmSwgaxTVyAwV8dDmJZPe5MJKpzWhvEIyGcS9fOMfRh-Bt6DrM4RD8jsYUGypFD1quPICP-f3pfdhM2eRE5bpB2SzvUQiC3cc7LMgQDNOozYQudEpnGyX8GbnOJ53FGbQBicdHtWQccS1SdHWCyGNjxnjUmsIQwPlPchEGgBru9uwtsUCnMzJdm6_NZxekRJzNAd2Sdhu9qoQ
    
    async with aiohttp.ClientSession() as session:
        # Извлекаем owner_id и audio_id из ссылки
        # Пример: https://vk.com/audio472117016_456240487
        parts = url.split('/audio')
        if len(parts) < 2:
            return None
        
        audio_params = parts[1].split('_')
        if len(audio_params) < 2:
            return None
        
        owner_id = audio_params[0]
        audio_id = audio_params[1].split('?')[0]  # Убираем лишние параметры
        
        # Делаем запрос к VK API
        params = {
            'v': '5.131',
            'access_token': VK_TOKEN,
            'audio_ids': f'{owner_id}_{audio_id}'
        }
        
        async with session.get(
            'https://api.vk.com/method/audio.getById',
            params=params
        ) as response:
            if response.status == 200:
                data = await response.json()
                if 'response' in data and len(data['response']) > 0:
                    track = data['response'][0]
                    return {
                        'artist': track.get('artist', ''),
                        'title': track.get('title', ''),
                        'url': track.get('url', '')
                    }
    return None

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id in user_temp_data:
        del user_temp_data[message.from_user.id]
    
    await message.answer(
        "🎉 <b>Привет! Я бот для создания общего плейлиста!</b>\n\n"
        "🎧 <b>Что я умею:</b>\n"
        "• Добавлять песни по ссылке\n"
        "• Показывать общий плейлист\n"
        "• Удалять песни из плейлиста\n\n"
        "👇 <b>Используй кнопки ниже:</b>",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

@dp.message(lambda msg: msg.text == "🎵 Плейлист")
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
    
    for i, (song_id, artist, title, url) in enumerate(songs, 1):
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
        "1. Нажми кнопку ➕ Добавить песню\n"
        "2. Отправь ссылку на песню (ВК, Яндекс, YouTube и т.д.)\n"
        "3. Напиши название в формате: Исполнитель - Название\n\n"
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
    await state.set_state(SongState.waiting_for_link)
    
    await message.answer(
        "📎 <b>Отправь ссылку на песню</b>\n\n"
        "Поддерживаются:\n"
        "• ВКонтакте (vk.com, vk.ru)\n"
        "• Яндекс.Музыка (music.yandex.ru)\n"
        "• YouTube (youtube.com)\n"
        "• Spotify, Deezer, Apple Music\n\n",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

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
            "Отправь ссылку из ВК, Яндекс.Музыки, YouTube и т.д.\n\n"
            "Или нажми на кнопку <b>Назад</b>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return
    
    # 🔥 Если это ссылка из ВК - пробуем автоматически получить инфо
    if 'vk.com' in text or 'vk.ru' in text:
        await message.answer("🔍 Распознаю трек из ВК...")
        
        vk_info = await get_vk_track_info(text)
        
        if vk_info and vk_info['artist'] and vk_info['title']:
            # Автоматически добавляем!
            artist = vk_info['artist']
            title = vk_info['title']
            
            add_song_to_db(artist, title, text)
            
            await state.clear()
            await message.answer(
                f"✅ <b>Песня добавлена автоматически!</b>\n\n"
                f"🎵 <b>{artist} - {title}</b>\n"
                f"🔗 {shorten_url(text)}",
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
            return
    
    # Для других ссылок или если не удалось распознать
    user_temp_data[message.from_user.id] = {'url': text}
    
    await state.set_state(SongState.waiting_for_title)
    await message.answer(
        "✅ Ссылка принята!\n\n"
        "Теперь напиши <b>название песни</b> в формате:\n"
        "<i>Исполнитель - Название</i>\n\n"
        "Например: Макс Корж - Жить в кайф\n\n"
        "Или нажми на кнопку <b>Назад</b>",
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
    
    add_song_to_db(artist, title, url)
    
    if message.from_user.id in user_temp_data:
        del user_temp_data[message.from_user.id]
    
    await state.clear()
    
    await message.answer(
        f"✅ <b>Песня добавлена!</b>\n\n"
        f"🎵 <b>{artist} - {title}</b>\n"
        f"🔗 {shorten_url(url) if url else 'Без ссылки'}",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

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
    
    for i, (song_id, artist, title, url) in enumerate(songs, 1):
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
            f"🗑 Песня #{list_number} удалена!",
            reply_markup=get_main_keyboard()
        )
    except ValueError:
        await message.answer(
            "❌ Напиши номер песни (число)!\n\n",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )

@dp.message(lambda msg: msg.text == " Назад")
async def cancel_action(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id in user_temp_data:
        del user_temp_data[message.from_user.id]
    await message.answer(
        " Действие отменено",
        reply_markup=get_main_keyboard()
    )

# ===== ЭКСПОРТ ПЛЕЙЛИСТА (только по секретной команде) =====
@dp.message(Command("export"))
async def cmd_export(message: types.Message, state: FSMContext):
    """Экспорт плейлиста"""
    await state.clear()
    
    songs = get_all_songs()
    
    if not songs:
        await message.answer(
            "🎵 Плейлист пуст! Нечего экспортировать.",
            reply_markup=get_main_keyboard()
        )
        return
    
    # === Файл 1: CSV для TuneMyMusic/Soundiiz ===
    csv_content = "Artist,Title\n"
    for song_id, artist, title, url in songs:
        artist_clean = artist.replace(",", " ")
        title_clean = title.replace(",", " ")
        csv_content += f"{artist_clean},{title_clean}\n"
    
    csv_file = io.BytesIO(csv_content.encode('utf-8-sig'))
    csv_file.name = "playlist_for_yandex.csv"
    
    # === Файл 2: TXT "Исполнитель - Название" ===
    txt_content = ""
    for song_id, artist, title, url in songs:
        txt_content += f"{artist} - {title}\n"
    
    txt_file = io.BytesIO(txt_content.encode('utf-8'))
    txt_file.name = "playlist.txt"
    
    # === Файл 3: Полная информация ===
    full_content = "🎧 ПЛЕЙЛИСТ\n 🎧"
    full_content += "=" * 50 + "\n\n"
    for i, (song_id, artist, title, url) in enumerate(songs, 1):
        full_content += f"{i}. {artist} - {title}\n"
        full_content += f"   {url}\n\n"
    
    full_file = io.BytesIO(full_content.encode('utf-8'))
    full_file.name = "playlist_full.txt"
    
    # Отправляем сообщение
    await message.answer(
        f"📤 <b>Экспорт плейлиста!</b>\n\n"
        f"🎵 Всего песен: <b>{len(songs)}</b>\n\n"
        f" Отправляю 3 файла:\n"
        f"1️⃣ <b>playlist_for_yandex.csv</b> - для импорта в Яндекс.Музыку\n"
        f"2️⃣ <b>playlist.txt</b> - простой список\n"
        f"3️⃣ <b>playlist_full.txt</b> - полный список со ссылками\n\n"
        f"👇 <b>Инструкция по импорту в Яндекс.Музыку:</b>",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )
    
    # Отправляем файлы
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
    
    # Инструкция
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
        "️ <b>Важно:</b> Не все песни могут найтись в Яндексе - "
        "сервис попытается найти похожие треки.",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

# ===== ЗАПУСК БОТА =====
async def main():
    print("🎵 Бот с ручным вводом запущен!")
    print("🎧 Готов добавлять песни!")
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 Бот остановлен.")
