import asyncio
import logging
import requests
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import TelegramError
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import re
from urllib.parse import urljoin
from typing import List, Dict, Optional

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
CONFIG = {
    'BOT_TOKEN': '8560322672:AAGKhZbVxEfIvwpsurMFC1VL70c2A3qKxok',
    'SPREADSHEET_ID': '1AsUaUiaNJSMrVITDFmVHmAiSrQO9Uvh-xM0aXtG-nbE',
    'BASE_URL': 'https://www.playground.ru',
    'NEWS_URL': 'https://www.playground.ru/news',
    'REQUEST_HEADERS': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    },
    'SCOPES': ['https://www.googleapis.com/auth/spreadsheets']
}


class CommentGenerator:
    def __init__(self):
        self.comments = {
            'gaming': ["🎮 Отличная игровая новость!", "🕹️ Интересный релиз!", "👾 Игровая индустрия не стоит на месте!"],
            'tech': ["🤖 Технологический прорыв!", "💻 Инновации в действии!", "🔬 Научный подход к играм!"],
            'review': ["⭐ Подробный обзор!", "📊 Аналитический подход!", "🎭 Глубокий разбор!"],
            'sale': ["💰 Отличная возможность сэкономить!", "🎁 Выгодное предложение!", "💸 Суперскидки!"],
            'update': ["🔄 Важное обновление!", "⚙️ Существенные изменения!", "🎪 Крупный апдейт!"],
            'general': ["📰 Интересная новость из мира игр!", "🎪 Яркое событие!", "🔔 Важная информация!"]
        }

    def generate_comment(self, news: Dict) -> str:
        title = news['title'].lower()
        description = news['description'].lower()

        categories = {
            'gaming': ['игра', 'гейм', 'game', 'релиз'],
            'tech': ['техно', 'tech', 'ai', 'ии', 'виртуальн'],
            'review': ['обзор', 'review', 'рецензия'],
            'sale': ['скидк', 'sale', 'распродаж'],
            'update': ['обновлен', 'update', 'патч']
        }

        for category, terms in categories.items():
            if any(term in title or term in description for term in terms):
                return random.choice(self.comments[category])
        return random.choice(self.comments['general'])


class GoogleSheetsManager:
    def __init__(self):
        self.credentials_file = 'credentials.json'
        self.sheet = None
        self.setup_google_sheets()

    def setup_google_sheets(self):
        try:
            if not os.path.exists(self.credentials_file):
                logger.error(f"Файл {self.credentials_file} не найден!")
                return

            # Пробуем разные кодировки для чтения файла
            try:
                with open(self.credentials_file, 'r', encoding='utf-8') as f:
                    creds_data = json.load(f)
            except UnicodeDecodeError:
                try:
                    with open(self.credentials_file, 'r', encoding='cp1251') as f:
                        creds_data = json.load(f)
                except UnicodeDecodeError:
                    with open(self.credentials_file, 'r', encoding='latin-1') as f:
                        creds_data = json.load(f)

            creds = Credentials.from_service_account_info(creds_data, scopes=CONFIG['SCOPES'])
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(CONFIG['SPREADSHEET_ID']).sheet1

            if not self.sheet.get_all_records():
                headers = ['ID', 'Заголовок', 'Ссылка', 'Дата', 'Описание', 'Комментарий', 'Дата добавления',
                           'Полный текст']
                self.sheet.append_row(headers)

            logger.info("✅ Успешно подключено к Google Таблице")
        except Exception as e:
            logger.error(f"❌ Ошибка при настройке Google Sheets: {e}")
            self.sheet = None

    def add_news_to_sheet(self, news_item: Dict, comment: str, full_text: str = "") -> bool:
        try:
            if not self.sheet:
                logger.warning("Google Таблица не доступна, пропускаем сохранение")
                return False

            all_records = self.sheet.get_all_records()
            last_id = len(all_records) if all_records else 0

            row_data = [
                last_id + 1,
                news_item['title'][:100],
                news_item['link'],
                news_item['date'][:50],
                news_item['description'][:200],
                comment[:100],
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                full_text[:1000]
            ]

            self.sheet.append_row(row_data)
            logger.info(f"✅ Новость добавлена: {news_item['title'][:30]}...")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка при добавлении новости: {e}")
            return False


class NewsParser:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(CONFIG['REQUEST_HEADERS'])

    def parse_news_list(self, limit: int = 10) -> List[Dict]:
        try:
            logger.info(f"🔄 Парсим {limit} новостей...")
            response = self.session.get(CONFIG['NEWS_URL'], timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            news_items = []

            # Поиск новостных блоков
            selectors = ['article.news-item', 'div.news-item', 'article.post', 'div.post', '.news-list article']
            news_blocks = []

            for selector in selectors:
                news_blocks = soup.select(selector)
                if news_blocks:
                    break

            if not news_blocks:
                news_blocks = soup.find_all('a', href=lambda x: x and '/news/' in x)

            for item in news_blocks[:limit]:
                news_data = self._parse_news_item(item)
                if news_data and news_data['title'] != 'Без заголовка':
                    news_items.append(news_data)

            logger.info(f"✅ Спарсено {len(news_items)} новостей")
            return news_items
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга: {e}")
            return []

    def _parse_news_item(self, item) -> Optional[Dict]:
        try:
            # Заголовок
            title_elem = item.find(['h2', 'h3', 'h1', '.title']) or item.find('a')
            title = title_elem.get_text(strip=True) if title_elem else "Без заголовка"

            # Ссылка
            link_elem = item.find('a')
            link = link_elem['href'] if link_elem and link_elem.get('href') else None
            if link and not link.startswith('http'):
                link = urljoin(CONFIG['BASE_URL'], link)

            if not link:
                return None

            # Дата
            date_elem = item.find(['time', '.date', '.news-date'])
            date = date_elem.get_text(strip=True) if date_elem else "Сегодня"

            # Описание
            desc_elem = item.find(['p', '.excerpt', '.description'])
            description = desc_elem.get_text(strip=True) if desc_elem else "Описание недоступно"

            # Изображение
            img_elem = item.find('img')
            image_url = None
            if img_elem:
                for attr in ['src', 'data-src']:
                    img_src = img_elem.get(attr)
                    if img_src:
                        if not img_src.startswith('http'):
                            img_src = urljoin(CONFIG['BASE_URL'], img_src)
                        image_url = img_src
                        break

            return {
                'title': title,
                'link': link,
                'date': date,
                'description': description,
                'image_url': image_url
            }
        except Exception as e:
            logger.error(f"Ошибка парсинга элемента: {e}")
            return None

    def parse_full_news(self, url: str) -> Dict:
        try:
            logger.info(f"🔄 Парсим полную новость: {url}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Поиск контента
            content_selectors = ['.article-content', '.post-content', '.entry-content', '.content', 'article .content']
            content_element = None

            for selector in content_selectors:
                content_element = soup.select_one(selector)
                if content_element:
                    break

            full_text = ""
            images = []

            if content_element:
                # Текст
                paragraphs = content_element.find_all('p')
                for p in paragraphs:
                    text = p.get_text(strip=True)
                    if len(text) > 30:
                        full_text += text + "\n\n"

                # Изображения
                for img in content_element.find_all('img'):
                    for attr in ['src', 'data-src']:
                        img_src = img.get(attr)
                        if img_src:
                            if not img_src.startswith('http'):
                                img_src = urljoin(url, img_src)
                            if img_src not in images:
                                images.append(img_src)
                            break

            # Очистка и ограничение текста
            full_text = re.sub(r'\n\s*\n', '\n\n', full_text).strip()
            if len(full_text) > 3500:
                full_text = full_text[:3500] + "...\n\n[Текст обрезан]"

            return {'full_text': full_text, 'images': images[:5]}
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга полной новости: {e}")
            return {'full_text': "Не удалось загрузить полный текст.", 'images': []}


class TelegramBot:
    def __init__(self):
        self.parser = NewsParser()
        self.sheets_manager = GoogleSheetsManager()
        self.comment_generator = CommentGenerator()
        self.application = Application.builder().token(CONFIG['BOT_TOKEN']).build()
        self.user_news_cache = {}
        self.setup_handlers()

    def setup_handlers(self):
        handlers = [
            CommandHandler("start", self.start),
            CommandHandler("news", self.get_news),
            CommandHandler("latest", self.latest_news),
            CommandHandler("full", self.full_news),
            CommandHandler("help", self.help_command),
            CallbackQueryHandler(self.button_handler)
        ]
        for handler in handlers:
            self.application.add_handler(handler)

    def _cache_news_for_user(self, user_id: int, news_items: List[Dict]):
        self.user_news_cache[user_id] = {'news': news_items, 'timestamp': datetime.now()}

    def _get_cached_news(self, user_id: int) -> Optional[List[Dict]]:
        if user_id in self.user_news_cache:
            cache_data = self.user_news_cache[user_id]
            if (datetime.now() - cache_data['timestamp']).total_seconds() < 600:
                return cache_data['news']
        return None

    def _create_main_keyboard(self):
        """Клавиатура для главного меню"""
        keyboard = [
            [
                InlineKeyboardButton("🎮 Свежие новости", callback_data="get_news_5"),
                InlineKeyboardButton("📰 Все новости", callback_data="get_news_10")
            ],
            [
                InlineKeyboardButton("📊 База данных",
                                     url=f"https://docs.google.com/spreadsheets/d/{CONFIG['SPREADSHEET_ID']}/edit"),
                InlineKeyboardButton("ℹ️ Помощь", callback_data="help")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def _create_news_keyboard(self, news_index: int, news_link: str):
        """Клавиатура для отдельной новости"""
        keyboard = [
            [
                InlineKeyboardButton("📖 Читать полностью", callback_data=f"full_{news_index}"),
                InlineKeyboardButton("🌐 На сайте", url=news_link)
            ],
            [
                InlineKeyboardButton("💾 Сохранить", callback_data=f"save_{news_index}"),
                InlineKeyboardButton("🔄 Следующая", callback_data=f"next_{news_index}")
            ],
            [
                InlineKeyboardButton("📋 К списку", callback_data="back_to_list"),
                InlineKeyboardButton("🏠 Главная", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def _create_list_keyboard(self, news_count: int, current_limit: int):
        """Клавиатура для списка новостей"""
        keyboard = []

        # Быстрый доступ к первым новостям
        if news_count > 0:
            quick_access = []
            for i in range(1, min(news_count, 6)):
                quick_access.append(InlineKeyboardButton(f"#{i}", callback_data=f"full_{i}"))
            keyboard.append(quick_access)

        keyboard.extend([
            [
                InlineKeyboardButton("🔄 Обновить", callback_data=f"get_news_{current_limit}"),
                InlineKeyboardButton("📥 Ещё", callback_data=f"get_news_{current_limit + 5}")
            ],
            [
                InlineKeyboardButton("💾 Сохранить все", callback_data="save_all"),
                InlineKeyboardButton("🏠 Главная", callback_data="main_menu")
            ]
        ])

        return InlineKeyboardMarkup(keyboard)

    def _create_full_news_keyboard(self, news_index: int, news_link: str, has_images: bool):
        """Клавиатура для полной новости"""
        keyboard = [
            [
                InlineKeyboardButton("🌐 Оригинал", url=news_link),
                InlineKeyboardButton("📸 Фото",
                                     callback_data=f"images_{news_index}") if has_images else InlineKeyboardButton(
                    "📸 Нет фото", callback_data="no_images")
            ],
            [
                InlineKeyboardButton("💾 Сохранить", callback_data=f"save_{news_index}"),
                InlineKeyboardButton("⬅️ Назад", callback_data="back_to_list")
            ],
            [
                InlineKeyboardButton("🏠 Главная", callback_data="main_menu"),
                InlineKeyboardButton("📰 Ещё новости", callback_data="get_news_5")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        try:
            text = """
🎮 *GameNews Bot* - Ваш гид по игровым новостям! 🌟

✨ *Что умею:*
• 📰 Парсить новости с Playground.ru
• 📖 Показывать полные тексты
• 🖼️ Отображать фотографии
• 💾 Сохранять в базу данных

🎯 Выберите действие ниже: 👇
            """
            await update.message.reply_text(
                text,
                reply_markup=self._create_main_keyboard(),
                parse_mode='Markdown'
            )
            logger.info(f"👤 Пользователь {update.effective_user.id} запустил бота")
        except Exception as e:
            logger.error(f"❌ Ошибка в start: {e}")
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        text = """
📋 *Доступные команды:*

/start - Главное меню
/news - 5 свежих новостей  
/latest - 10 новостей
/full N - Полный текст новости №N

💡 Используйте кнопки для удобной навигации!
        """
        await update.message.reply_text(text, parse_mode='Markdown')

    async def get_news(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать 5 последних новостей"""
        await self._send_news_list(update, 5)

    async def latest_news(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать 10 последних новостей"""
        await self._send_news_list(update, 10)

    async def _send_news_list(self, update: Update, limit: int):
        """Отправка списка новостей"""
        try:
            user_id = update.effective_user.id
            message = await update.message.reply_text("🔄 Загружаю новости... ⏳")

            # Пробуем получить из кэша
            news_items = self._get_cached_news(user_id)
            if not news_items or len(news_items) < limit:
                news_items = self.parser.parse_news_list(limit=limit)
                if news_items:
                    self._cache_news_for_user(user_id, news_items)

            if not news_items:
                await message.edit_text("❌ Не удалось загрузить новости. Попробуйте позже.")
                return

            # Отправляем каждую новость
            success_count = 0
            for i, news in enumerate(news_items, 1):
                if await self._send_single_news(update, news, i, len(news_items)):
                    success_count += 1
                await asyncio.sleep(1)  # Задержка между сообщениями

            # Обновляем сообщение о статусе
            if success_count > 0:
                await message.edit_text(
                    f"✅ Успешно загружено {success_count} новостей!\n\nИспользуйте кнопки для навигации: 👇",
                    reply_markup=self._create_list_keyboard(success_count, limit)
                )
            else:
                await message.edit_text("❌ Не удалось отправить ни одной новости.")

        except Exception as e:
            logger.error(f"❌ Ошибка в _send_news_list: {e}")
            await update.message.reply_text("❌ Произошла ошибка при загрузке новостей.")

    async def _send_single_news(self, update: Update, news: Dict, index: int, total: int) -> bool:
        """Отправка одной новости"""
        try:
            comment = self.comment_generator.generate_comment(news)
            text = f"""📰 *{news['title']}*

{news['description']}

━━━━━━━━━━━━━━
📅 *Дата:* {news['date']}
💬 *Комментарий:* {comment}
🔢 *Номер:* {index}/{total}

🎯 Выберите действие: 👇"""

            keyboard = self._create_news_keyboard(index, news['link'])

            # Пробуем отправить с фото
            if news.get('image_url'):
                try:
                    await update.message.reply_photo(
                        news['image_url'],
                        caption=text,
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
                    return True
                except TelegramError as e:
                    logger.warning(f"⚠️ Не удалось отправить фото: {e}")

            # Fallback: только текст
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка отправки новости {index}: {e}")
            return False

    async def full_news(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать полный текст конкретной новости"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "❌ Укажите номер новости.\nПример: `/full 1`",
                    parse_mode='Markdown'
                )
                return

            news_number = int(context.args[0])
            user_id = update.effective_user.id
            news_items = self._get_cached_news(user_id)

            if not news_items:
                await update.message.reply_text(
                    "ℹ️ Сначала получите список новостей командой /news или /latest",
                    reply_markup=self._create_main_keyboard()
                )
                return

            if news_number < 1 or news_number > len(news_items):
                await update.message.reply_text(
                    f"❌ Новость №{news_number} не найдена. Доступно: 1-{len(news_items)}"
                )
                return

            await self._send_full_news(update, news_items[news_number - 1], news_number)

        except ValueError:
            await update.message.reply_text("❌ Укажите корректный номер новости")
        except Exception as e:
            logger.error(f"❌ Ошибка в full_news: {e}")
            await update.message.reply_text("❌ Произошла ошибка")

    async def _send_full_news(self, update: Update, news: Dict, news_number: int):
        """Отправка полного текста новости"""
        try:
            loading_msg = await update.message.reply_text("🔄 Загружаю полный текст... 📖")

            content = self.parser.parse_full_news(news['link'])
            comment = self.comment_generator.generate_comment(news)

            # Сохраняем в базу
            self.sheets_manager.add_news_to_sheet(news, comment, content['full_text'])

            text = f"""📖 *{news['title']}*

{content['full_text']}

━━━━━━━━━━━━━━
📅 *Опубликовано:* {news['date']}
💬 *Комментарий:* {comment}
🔗 *Источник:* [Playground.ru]({news['link']})
🎯 *Номер:* #{news_number}"""

            await loading_msg.delete()

            has_images = len(content['images']) > 0
            keyboard = self._create_full_news_keyboard(news_number, news['link'], has_images)

            # Отправляем с первым изображением если есть
            if has_images and content['images']:
                try:
                    await update.message.reply_photo(
                        content['images'][0],
                        caption=text,
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось отправить фото: {e}")
                    await update.message.reply_text(
                        text,
                        reply_markup=keyboard,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
            else:
                await update.message.reply_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )

            logger.info(f"✅ Полная новость {news_number} отправлена")

        except Exception as e:
            logger.error(f"❌ Ошибка в _send_full_news: {e}")
            await update.message.reply_text("❌ Не удалось загрузить полный текст")

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на кнопки"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        data = query.data

        try:
            if data == "main_menu":
                await self._handle_main_menu(query)
            elif data == "help":
                await self._handle_help(query)
            elif data == "refresh":
                await self._handle_refresh(query)
            elif data == "back_to_list":
                await self._handle_back_to_list(query)
            elif data.startswith("get_news_"):
                await self._handle_get_news(query, int(data.split('_')[2]))
            elif data.startswith("full_"):
                await self._handle_full_news(query, int(data.split('_')[1]))
            elif data.startswith("save_"):
                await self._handle_save_news(query, int(data.split('_')[1]))
            elif data == "save_all":
                await self._handle_save_all(query)
            elif data.startswith("next_"):
                await self._handle_next_news(query, int(data.split('_')[1]))
            elif data.startswith("images_"):
                await self._handle_show_images(query, int(data.split('_')[1]))
            elif data == "no_images":
                await query.answer("📸 В этой новости нет дополнительных фото", show_alert=True)

        except Exception as e:
            logger.error(f"❌ Ошибка обработки кнопки {data}: {e}")
            await query.answer("❌ Произошла ошибка")

    async def _handle_main_menu(self, query):
        await query.edit_message_text(
            "🎮 *Главное меню GameNews Bot* 🎯\n\nВыберите действие: 👇",
            reply_markup=self._create_main_keyboard(),
            parse_mode='Markdown'
        )

    async def _handle_help(self, query):
        text = """
🆘 *Помощь по боту*

🎯 *Основные функции:*
• 📰 Получение свежих новостей
• 📖 Чтение полных текстов  
• 🖼️ Просмотр фотографий
• 💾 Сохранение в базу данных

💡 Используйте кнопки для навигации!
        """
        keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def _handle_refresh(self, query):
        await query.answer("🔄 Обновляю...")
        await self._handle_main_menu(query)

    async def _handle_back_to_list(self, query):
        user_id = query.from_user.id
        news_items = self._get_cached_news(user_id)

        if not news_items:
            await query.edit_message_text(
                "📋 Нет сохраненных новостей\n\nПолучите свежие новости! 👇",
                reply_markup=self._create_main_keyboard()
            )
            return

        text = f"📋 *Список новостей ({len(news_items)} шт.)*\n\n" + "\n".join(
            f"#{i}. {news['title'][:50]}..." for i, news in enumerate(news_items, 1)
        )
        await query.edit_message_text(
            text,
            reply_markup=self._create_list_keyboard(len(news_items), len(news_items)),
            parse_mode='Markdown'
        )

    async def _handle_get_news(self, query, limit: int):
        await query.edit_message_text("🔄 Загружаю новости... ⏳")
        user_id = query.from_user.id
        news_items = self.parser.parse_news_list(limit=limit)

        if news_items:
            self._cache_news_for_user(user_id, news_items)
            text = f"📰 *Последние {len(news_items)} новостей:*\n\n" + "\n".join(
                f"#{i}. {news['title']}\n   📅 {news['date']}\n" for i, news in enumerate(news_items, 1)
            )
            await query.edit_message_text(
                text,
                reply_markup=self._create_list_keyboard(len(news_items), limit),
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
        else:
            await query.edit_message_text("❌ Не удалось загрузить новости")

    async def _handle_full_news(self, query, news_number: int):
        user_id = query.from_user.id
        news_items = self._get_cached_news(user_id)

        if not news_items or news_number > len(news_items):
            await query.answer("❌ Новость не найдена")
            return

        await query.edit_message_text("🔄 Загружаю полный текст... 📖")
        news = news_items[news_number - 1]
        content = self.parser.parse_full_news(news['link'])
        comment = self.comment_generator.generate_comment(news)

        text = f"""📖 *{news['title']}*

{content['full_text']}

━━━━━━━━━━━━━━
📅 *Опубликовано:* {news['date']}
💬 *Комментарий:* {comment}
🔗 *Источник:* [Playground.ru]({news['link']})"""

        # Сохраняем в базу
        self.sheets_manager.add_news_to_sheet(news, comment, content['full_text'])

        has_images = len(content['images']) > 0
        keyboard = self._create_full_news_keyboard(news_number, news['link'], has_images)

        # Отправляем новое сообщение
        if has_images and content['images']:
            try:
                await query.message.reply_photo(
                    content['images'][0],
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
            except:
                await query.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown',
                                               disable_web_page_preview=True)
        else:
            await query.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown',
                                           disable_web_page_preview=True)

        await query.edit_message_text(f"✅ *Новость #{news_number} загружена!* 📨", parse_mode='Markdown')

    async def _handle_save_news(self, query, news_number: int):
        user_id = query.from_user.id
        news_items = self._get_cached_news(user_id)

        if news_items and news_number <= len(news_items):
            news = news_items[news_number - 1]
            comment = self.comment_generator.generate_comment(news)
            content = self.parser.parse_full_news(news['link'])
            success = self.sheets_manager.add_news_to_sheet(news, comment, content['full_text'])
            await query.answer("✅ Сохранено в базу! 💾" if success else "❌ Ошибка сохранения")
        else:
            await query.answer("❌ Новость не найдена")

    async def _handle_save_all(self, query):
        user_id = query.from_user.id
        news_items = self._get_cached_news(user_id)

        if not news_items:
            await query.answer("❌ Нет новостей для сохранения")
            return

        saved_count = 0
        for news in news_items:
            comment = self.comment_generator.generate_comment(news)
            content = self.parser.parse_full_news(news['link'])
            if self.sheets_manager.add_news_to_sheet(news, comment, content['full_text']):
                saved_count += 1
            await asyncio.sleep(0.5)

        await query.answer(f"✅ Сохранено {saved_count}/{len(news_items)} новостей! 💾", show_alert=True)

    async def _handle_next_news(self, query, current_index: int):
        user_id = query.from_user.id
        news_items = self._get_cached_news(user_id)

        if not news_items:
            await query.answer("❌ Нет доступных новостей")
            return

        next_index = current_index + 1
        if next_index > len(news_items):
            await query.answer("🎉 Это последняя новость в списке!", show_alert=True)
            return

        news = news_items[next_index - 1]
        await self._send_single_news_from_query(query, news, next_index, len(news_items))

    async def _handle_show_images(self, query, news_number: int):
        user_id = query.from_user.id
        news_items = self._get_cached_news(user_id)

        if not news_items or news_number > len(news_items):
            await query.answer("❌ Новость не найдена")
            return

        news = news_items[news_number - 1]
        content = self.parser.parse_full_news(news['link'])
        images = content['images'][1:4]  # Пропускаем первое, берем следующие 3

        if not images:
            await query.answer("📸 Дополнительных фото нет", show_alert=True)
            return

        sent_count = 0
        for img in images:
            try:
                await query.message.reply_photo(img)
                sent_count += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"⚠️ Не удалось отправить фото: {e}")

        await query.answer(f"📸 Отправлено {sent_count} фото", show_alert=True)

    async def _send_single_news_from_query(self, query, news: Dict, index: int, total: int):
        """Отправка одной новости из callback query"""
        try:
            comment = self.comment_generator.generate_comment(news)
            text = f"""📰 *{news['title']}*

{news['description']}

━━━━━━━━━━━━━━
📅 *Дата:* {news['date']}
💬 *Комментарий:* {comment}
🔢 *Номер:* {index}/{total}

🎯 Выберите действие: 👇"""

            keyboard = self._create_news_keyboard(index, news['link'])

            if news.get('image_url'):
                try:
                    await query.message.reply_photo(
                        news['image_url'],
                        caption=text,
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
                    return
                except TelegramError:
                    pass

            await query.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"❌ Ошибка отправки новости: {e}")
            await query.message.reply_text("❌ Ошибка при загрузке новости")

    def run(self):
        """Запуск бота"""
        try:
            logger.info("🤖 Запускаю бота...")
            print("=" * 50)
            print("🎮 GAMENEWS BOT ЗАПУЩЕН! 🚀")
            print(f"📊 Google Sheets: {'✅ Подключено' if self.sheets_manager.sheet else '❌ Ошибка'}")
            print("🌐 Парсер: ✅ Активен")
            print("💬 Комментарии: ✅ Активны")
            print("🎯 Кнопки: ✅ Активны")
            print("=" * 50)

            self.application.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES
            )
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
            print(f"❌ Критическая ошибка: {e}")


def main():
    """Основная функция"""
    try:
        bot = TelegramBot()
        bot.run()
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")


if __name__ == "__main__":
    main()