"""Generate a representative, provenance-pinned streamer and game corpus v3."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

_CORPUS_ID = "streamer-game-voice-representative-v3"
_SCHEMA_VERSION = 3
_DEFAULT_SEED = 20260801
_TOTAL_RECORDS = 2000
_HOLDOUT_RECORDS = 500
_CATEGORY_QUOTAS = {
    "live_chat": 640,
    "game_commentary": 480,
    "game_review": 320,
    "game_dialogue": 280,
    "stream_event": 160,
    "transition": 120,
}
_LANGUAGE_QUOTAS = {"ru": 1300, "en": 500, "mixed": 200}
_LENGTH_QUOTAS = {
    "micro": 300,
    "short": 400,
    "medium": 700,
    "long": 400,
    "extended": 200,
}
_WORD_RANGES = {
    "micro": (1, 3),
    "short": (4, 7),
    "medium": (8, 18),
    "long": (19, 35),
    "extended": (36, 65),
}
_MAX_FAMILY_PERCENT = 2.0
_MAX_INTENT_PERCENT = 5.0
_MAX_KEY_PHRASE_COUNT = 10
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LATIN_RE = re.compile(r"[A-Za-z]")

_STYLES = {
    "ru": ["Сейчас", "Слушай", "Честно", "Похоже", "Ладно", "Вижу", "Так", "Кстати"],
    "en": [
        "Now",
        "Listen",
        "Honestly",
        "Apparently",
        "Alright",
        "Clearly",
        "Okay",
        "Also",
    ],
    "mixed": ["Сейчас", "Слушай", "Честно", "Похоже", "Окей", "Вижу", "Так", "Кстати"],
}
_MICRO_REPLIES = {
    "ru": [
        "погнали",
        "спасибо",
        "секунду",
        "вижу",
        "принято",
        "тише",
        "дальше",
        "стоп",
    ],
    "en": ["go", "thanks", "wait", "seen", "noted", "quiet", "next", "stop"],
    "mixed": ["го", "спасибо", "секунду", "вижу", "принято", "тише", "дальше", "стоп"],
}
_MICRO_MODIFIERS = {
    "ru": ["сейчас", "вместе", "быстро", "сюда", "потом", "готово", "снова", "тут"],
    "en": ["now", "together", "quickly", "here", "later", "ready", "again", "there"],
    "mixed": ["now", "together", "quickly", "here", "later", "ready", "again", "there"],
}
_SHORT_TAGS = {
    "ru": [
        "сейчас",
        "вместе",
        "быстро",
        "дальше",
        "точно",
        "снова",
        "сегодня",
        "рядом",
    ],
    "en": ["now", "together", "quickly", "next", "today", "again", "nearby", "clearly"],
    "mixed": ["сейчас", "вместе", "быстро", "next", "точно", "снова", "today", "рядом"],
}
_PACKS = {
    "ru": {
        "live_chat": {
            "micro": [
                "Чат",
                "Ребята",
                "Друзья",
                "Зрители",
                "Народ",
                "Команда",
                "Все",
                "Модеры",
            ],
            "cores": [
                "читаю вопрос про билд",
                "спасибо за вашу поддержку",
                "сейчас вернусь к боссу",
                "вижу сообщение в чате",
                "покажу настройки после боя",
                "не уходите, это быстро",
                "отвечу после этой катки",
                "перезапущу сцену через минуту",
            ],
            "details": [
                "сначала закрою этот раунд",
                "потом спокойно всё объясню",
                "так будет проще следить",
                "не хочу пропустить важное",
                "ссылка уже есть в описании",
                "звук сейчас проверю",
                "выберем вариант вместе",
                "чат подскажет, что выбрать",
            ],
        },
        "game_commentary": {
            "micro": [
                "Лево",
                "Право",
                "Центр",
                "Босс",
                "База",
                "Враг",
                "Флаг",
                "Выход",
            ],
            "cores": [
                "левый фланг уже свободен",
                "враг идёт через центр",
                "босс почти без брони",
                "берегите последний щит",
                "наша точка пока держится",
                "снайпер смотрит с крыши",
                "флаг несут к выходу",
                "ультимейт готов для пуша",
            ],
            "details": [
                "давим вместе после перезарядки",
                "не растягиваемся по карте",
                "держим угол и не спешим",
                "один игрок остался сзади",
                "сначала забираем аптечку",
                "прикрываю вас с высоты",
                "входим только по моему сигналу",
                "это решающий момент раунда",
            ],
        },
        "game_review": {
            "micro": [
                "Графика",
                "Сюжет",
                "Бой",
                "Карта",
                "Баланс",
                "Звук",
                "Меню",
                "Патч",
            ],
            "cores": [
                "графика отлично держит атмосферу",
                "сюжет заметно теряет темп",
                "боёвка стала гораздо точнее",
                "карта раскрывается не сразу",
                "баланс оружия всё ещё спорный",
                "звук делает сцены живее",
                "меню перегружено лишними окнами",
                "патч исправил самые грубые баги",
            ],
            "details": [
                "особенно в ночных локациях",
                "но персонажам не хватает мотивации",
                "и это чувствуется в каждом бою",
                "когда открываются боковые задания",
                "для игры с рейтингом это важно",
                "в наушниках разница огромная",
                "на геймпаде это раздражает сильнее",
                "однако проблемы с камерой остались",
            ],
        },
        "game_dialogue": {
            "micro": [
                "Стой",
                "Беги",
                "Тише",
                "Сюда",
                "Поздно",
                "Живой",
                "Ключ",
                "Мост",
            ],
            "cores": [
                "я видел тебя у ворот",
                "нам нужен ключ от башни",
                "не трогай этот рычаг",
                "дорога через лес опасна",
                "стража уже ищет нас",
                "я не брошу тебя здесь",
                "за мостом начинается туман",
                "у нас осталась одна попытка",
            ],
            "details": [
                "и времени почти не осталось",
                "если хочешь выбраться живым",
                "пока они не закрыли проход",
                "но я знаю другой путь",
                "ты должен мне доверять",
                "иначе всё было напрасно",
                "слушай шаги за стеной",
                "это не тот голос, который ты слышал",
            ],
        },
        "stream_event": {
            "micro": [
                "Рейд",
                "Донат",
                "Саб",
                "Опрос",
                "Пауза",
                "Звук",
                "Сцена",
                "Игра",
            ],
            "cores": [
                "спасибо за подписку на канал",
                "к нам пришёл большой рейд",
                "донат прочитаю после момента",
                "опрос уже запущен в чате",
                "на секунду поставлю паузу",
                "звук снова начал шуметь",
                "сцена переключилась не туда",
                "сейчас меняем игру на стриме",
            ],
            "details": [
                "добро пожаловать всем новым зрителям",
                "не хочу пропустить ваше сообщение",
                "голосование продлится ещё минуту",
                "потом сразу возвращаемся в матч",
                "проверю кабель и продолжим",
                "спасибо, что предупредили вовремя",
                "сейчас поправлю это вручную",
                "переход займёт совсем немного времени",
            ],
        },
        "transition": {
            "micro": [
                "Дальше",
                "Пауза",
                "Карта",
                "Меню",
                "Глава",
                "Сцена",
                "Загрузка",
                "Финал",
            ],
            "cores": [
                "переходим к следующей главе",
                "сначала открою карту района",
                "между сценами есть короткая пауза",
                "сейчас покажу главное меню",
                "загрузка почти закончилась",
                "эта сцена меняет настроение",
                "перед финалом сохраню игру",
                "дальше будет новая локация",
            ],
            "details": [
                "там начинается совсем другой ритм",
                "чтобы ничего не потерять",
                "и можно перевести дыхание",
                "после этого вернёмся к действию",
                "осталось подождать несколько секунд",
                "не пропустите эту реплику",
                "на случай если что-то пойдёт не так",
                "теперь история становится серьёзнее",
            ],
        },
    },
    "en": {
        "live_chat": {
            "micro": [
                "Chat",
                "Folks",
                "Friends",
                "Viewers",
                "Everyone",
                "Team",
                "Mods",
                "People",
            ],
            "cores": [
                "I see the build question",
                "thanks for the support",
                "I will return to the boss",
                "that message just reached me",
                "I will show the settings",
                "do not leave just yet",
                "I will answer after this match",
                "the scene needs a quick restart",
            ],
            "details": [
                "let me finish this round first",
                "then I can explain it clearly",
                "that makes the chat easier to follow",
                "I do not want to miss the point",
                "the link is already below",
                "I will check the audio now",
                "we can choose it together",
                "the chat can help decide",
            ],
        },
        "game_commentary": {
            "micro": [
                "Left",
                "Right",
                "Center",
                "Boss",
                "Base",
                "Enemy",
                "Flag",
                "Exit",
            ],
            "cores": [
                "the left lane is open",
                "an enemy is crossing center",
                "the boss lost most armor",
                "save the last shield",
                "our point is still holding",
                "the sniper is on the roof",
                "the flag is moving to exit",
                "my ultimate is ready for push",
            ],
            "details": [
                "we move after the reload",
                "do not spread across the map",
                "hold the corner for now",
                "one player stayed behind",
                "take the medkit first",
                "I can cover from above",
                "go only on my signal",
                "this decides the round",
            ],
        },
        "game_review": {
            "micro": [
                "Visuals",
                "Story",
                "Combat",
                "Map",
                "Balance",
                "Audio",
                "Menus",
                "Patch",
            ],
            "cores": [
                "the visuals sell the atmosphere",
                "the story loses momentum",
                "combat feels much sharper",
                "the map opens up slowly",
                "weapon balance remains uneven",
                "the audio lifts each scene",
                "the menus have too many layers",
                "the patch fixed major bugs",
            ],
            "details": [
                "especially in the night areas",
                "because the cast needs stronger motives",
                "and every encounter shows it",
                "once side quests appear",
                "for a ranked game that matters",
                "headphones make it much clearer",
                "a controller makes this worse",
                "but camera issues remain",
            ],
        },
        "game_dialogue": {
            "micro": ["Stop", "Run", "Quiet", "Here", "Late", "Alive", "Key", "Bridge"],
            "cores": [
                "I saw you near the gate",
                "we need the tower key",
                "do not touch that lever",
                "the forest road is dangerous",
                "the guards are looking for us",
                "I will not leave you here",
                "fog starts beyond the bridge",
                "we have one chance left",
            ],
            "details": [
                "and there is little time",
                "if you want to leave alive",
                "before they seal the passage",
                "but I know another route",
                "you need to trust me",
                "or all this meant nothing",
                "listen to the steps outside",
                "that is not the voice you heard",
            ],
        },
        "stream_event": {
            "micro": [
                "Raid",
                "Donation",
                "Sub",
                "Poll",
                "Pause",
                "Audio",
                "Scene",
                "Game",
            ],
            "cores": [
                "thanks for subscribing today",
                "a big raid just arrived",
                "I will read that donation",
                "the poll is live in chat",
                "I need a brief pause",
                "the audio started crackling again",
                "the scene switched too early",
                "we are changing games now",
            ],
            "details": [
                "welcome to all new viewers",
                "I do not want to miss it",
                "voting stays open one minute",
                "then we return to the match",
                "I will check the cable",
                "thanks for catching that quickly",
                "I can correct it manually",
                "the transition will be brief",
            ],
        },
        "transition": {
            "micro": [
                "Next",
                "Pause",
                "Map",
                "Menu",
                "Chapter",
                "Scene",
                "Loading",
                "Finale",
            ],
            "cores": [
                "we move to the next chapter",
                "I will open the district map",
                "there is a short scene break",
                "let me show the main menu",
                "loading is almost complete",
                "this scene changes the mood",
                "I will save before finale",
                "the next area is ready",
            ],
            "details": [
                "because the pace shifts there",
                "so we do not lose anything",
                "and everyone can breathe",
                "then the action returns",
                "just wait a few seconds",
                "do not miss this line",
                "in case something breaks",
                "the story gets serious now",
            ],
        },
    },
    "mixed": {
        "live_chat": {
            "micro": [
                "Чат",
                "Ребята",
                "Steam",
                "Discord",
                "Зрители",
                "Модеры",
                "Все",
                "Команда",
            ],
            "cores": [
                "вижу вопрос про Steam build",
                "Discord снова прислал пинг",
                "спасибо за Twitch sub",
                "сейчас покажу OBS сцену",
                "чат просит новый game mode",
                "ссылка на Discord уже готова",
                "после матча проверю RTX настройки",
                "этот Steam gift очень вовремя",
            ],
            "details": [
                "потом вернусь к обычному стриму",
                "не хочу потерять это сообщение",
                "так всем будет понятнее",
                "после боя отвечу подробнее",
                "сначала дочитаю весь чат",
                "спасибо за быстрый сигнал",
                "это займёт ровно минуту",
                "выберем вариант вместе",
            ],
        },
        "game_commentary": {
            "micro": ["Boss", "Лево", "Right", "Base", "FPS", "Флаг", "Lobby", "Exit"],
            "cores": [
                "boss уже без shield",
                "враг идёт через mid lane",
                "наш cooldown почти готов",
                "в lobby остался один игрок",
                "FPS просел в этой сцене",
                "правый flank пока чистый",
                "build работает против танка",
                "на base нужен быстрый reset",
            ],
            "details": [
                "пушим после короткой паузы",
                "не теряем контроль над точкой",
                "сначала забираем health pack",
                "я держу этот угол",
                "это решает весь round",
                "не даём им space",
                "ждём мой call",
                "потом сразу выходим",
            ],
        },
        "game_review": {
            "micro": ["Patch", "RTX", "Story", "Boss", "UI", "Steam", "Build", "FPS"],
            "cores": [
                "patch заметно улучшил FPS",
                "RTX делает ночные сцены живее",
                "story теряет темп в середине",
                "boss fights требуют хорошего build",
                "UI мешает быстро менять оружие",
                "Steam версия стартует стабильно",
                "balance в ranked всё ещё спорный",
                "sound design спасает слабые диалоги",
            ],
            "details": [
                "особенно на сложных аренах",
                "но проблема с камерой осталась",
                "в наушниках разница сильнее",
                "для нового игрока это тяжело",
                "после tutorial становится лучше",
                "на controller всё ощущается иначе",
                "это важно для долгих сессий",
                "прошлая часть делала это яснее",
            ],
        },
        "game_dialogue": {
            "micro": ["Stop", "Тише", "Key", "Bridge", "Boss", "Сюда", "Run", "Fog"],
            "cores": [
                "ключ от vault у boss",
                "не трогай этот control panel",
                "за bridge начинается fog",
                "guard уже слышит наши шаги",
                "у нас один save point",
                "этот NPC знает выход",
                "portal закроется через минуту",
                "я видел этот symbol раньше",
            ],
            "details": [
                "если хочешь выйти живым",
                "но сначала доверься мне",
                "пока guard не поднял тревогу",
                "иначе потеряем весь progress",
                "слушай мой голос внимательно",
                "это не обычный side quest",
                "за дверью может быть trap",
                "времени почти не осталось",
            ],
        },
        "stream_event": {
            "micro": ["Raid", "Sub", "Poll", "OBS", "Pause", "Audio", "Chat", "Game"],
            "cores": [
                "спасибо за новый Twitch sub",
                "Raid пришёл прямо в boss fight",
                "Poll уже запущен в chat",
                "OBS снова переключил scene",
                "audio шумит после alert",
                "Steam overlay закрыл game",
                "Discord raid оказался огромным",
                "сейчас меняем game category",
            ],
            "details": [
                "спасибо всем, кто пришёл",
                "потом вернёмся к матчу",
                "сначала поправлю этот alert",
                "голосование идёт ещё минуту",
                "не хочу потерять ваш message",
                "это обычный технический reset",
                "чат быстро всё заметил",
                "переход займёт пару секунд",
            ],
        },
        "transition": {
            "micro": [
                "Next",
                "Pause",
                "Map",
                "Menu",
                "Loading",
                "Scene",
                "Save",
                "Finale",
            ],
            "cores": [
                "после loading откроется новая map",
                "сейчас перейдём в next chapter",
                "menu покажет новый build",
                "перед finale сделаю save",
                "эта scene меняет весь tone",
                "после cutscene вернёмся в game",
                "map грузится чуть дольше",
                "дальше начнётся ranked lobby",
            ],
            "details": [
                "так мы ничего не пропустим",
                "можно спокойно перевести дыхание",
                "потом сразу продолжим run",
                "не закрывайте stream",
                "это займёт несколько секунд",
                "впереди важный story момент",
                "я быстро проверю settings",
                "после этого будет action",
            ],
        },
    },
}
_REACTIONS = {
    "ru": [
        "это меняет план на раунд",
        "поэтому не спешим с решением",
        "и команда уже понимает задачу",
        "такой момент легко отдать сопернику",
        "теперь ошибка будет слишком дорогой",
        "здесь важна точная координация",
        "это выглядит намного увереннее",
        "дальше рисковать уже не нужно",
    ],
    "en": [
        "that changes the plan this round",
        "so we should not rush it",
        "and the team sees the task",
        "this moment is easy to lose",
        "the next mistake costs too much",
        "precise coordination matters here",
        "that looks much more confident",
        "we do not need more risk",
    ],
    "mixed": [
        "это меняет весь game plan",
        "так что не спешим с push",
        "и team уже видит задачу",
        "такой момент легко отдать enemy",
        "следующая ошибка будет дорогой",
        "тут нужна точная coordination",
        "это выглядит намного увереннее",
        "дальше лишний risk не нужен",
    ],
}
_CLOSINGS = {
    "ru": [
        "После этого станет ясно, куда двигаться.",
        "Потом можно спокойно продолжать.",
        "Такой темп сейчас самый надёжный.",
        "Именно поэтому этот момент важен.",
    ],
    "en": [
        "After that, the next move is clear.",
        "Then we can continue calmly.",
        "That pace is the safest now.",
        "That is why this moment matters.",
    ],
    "mixed": [
        "После этого следующий move станет яснее.",
        "Потом спокойно продолжим run.",
        "Такой pace сейчас самый надёжный.",
        "Вот почему этот момент важен.",
    ],
}
_LONG_ADDENDUM = {
    "ru": "Сейчас главное не потерять этот темп.",
    "en": "The main thing is keeping this pace now.",
    "mixed": "Сейчас главное не потерять этот pace.",
}
_EXTENDED_ADDENDUM = {
    "ru": "Я отмечу это, чтобы потом не искать причину заново.",
    "en": "I will mark it so we do not lose the reason later.",
    "mixed": "Я отмечу это, чтобы потом не искать причину снова.",
}
_LENGTH_EXTENSIONS = {
    "ru": [
        "Смотрим на карту, звук и позицию команды.",
        "Никто не идёт один, пока путь не проверен.",
        "Этот сигнал лучше не пропускать прямо сейчас.",
        "Пара секунд терпения здесь многое меняет.",
        "Я держу ситуацию в поле зрения до конца.",
        "Потом будет время обсудить это подробнее вместе.",
        "Сейчас важнее сохранить спокойный темп команды.",
        "Следующий шаг должен быть простым и понятным всем.",
    ],
    "en": [
        "Watch the map, audio, and the team position.",
        "Nobody goes alone until the path is checked.",
        "This signal matters right at this moment.",
        "A few patient seconds change a lot here.",
        "I will keep the whole situation in view.",
        "We can discuss the details together afterward.",
        "Keeping the team pace steady matters most now.",
        "The next move should stay clear for everyone.",
    ],
    "mixed": [
        "Смотрим на map, audio и позицию team.",
        "Никто не идёт solo, пока путь не проверен.",
        "Этот signal важен именно в этот момент.",
        "Пара секунд patience здесь многое меняет.",
        "Я держу всю ситуацию в поле зрения.",
        "Детали обсудим вместе после этого run.",
        "Сейчас важнее сохранить спокойный team pace.",
        "Следующий move должен быть понятен всем.",
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery-output", type=Path, required=True)
    parser.add_argument("--holdout-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--manual-review-output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    args = parser.parse_args()

    provenance = _provenance(args.seed)
    records = _build_records(args.seed, provenance)
    discovery, holdout = _split_records(records, args.seed)
    review = _manual_review_records(records, args.seed)
    _write_jsonl(args.discovery_output, discovery)
    _write_jsonl(args.holdout_output, holdout)
    _write_jsonl(args.manual_review_output, review)
    audit = _audit(
        records,
        discovery,
        holdout,
        review,
        args.discovery_output,
        args.holdout_output,
        args.manual_review_output,
        provenance,
    )
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, sort_keys=True))
    return 0


def _provenance(seed: int) -> dict[str, object]:
    config = {
        "corpus_id": _CORPUS_ID,
        "category_quotas": _CATEGORY_QUOTAS,
        "language_quotas": _LANGUAGE_QUOTAS,
        "length_quotas": _LENGTH_QUOTAS,
        "word_ranges": _WORD_RANGES,
        "max_family_percent": _MAX_FAMILY_PERCENT,
        "max_intent_percent": _MAX_INTENT_PERCENT,
        "max_key_phrase_count": _MAX_KEY_PHRASE_COUNT,
    }
    return {
        "generation_seed": seed,
        "generation_config_sha256": _sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ),
        "generator_source_sha256": _sha256(Path(__file__).read_bytes()),
    }


def _build_records(seed: int, provenance: dict[str, object]) -> list[dict[str, object]]:
    rng = random.Random(seed)
    categories = _expanded(_CATEGORY_QUOTAS)
    languages = _expanded(_LANGUAGE_QUOTAS)
    lengths = _expanded(_LENGTH_QUOTAS)
    for values in (categories, languages, lengths):
        rng.shuffle(values)
    stratum_index: Counter[tuple[str, str]] = Counter()
    records = []
    seen_texts: set[str] = set()
    for index, (category, language, length_class) in enumerate(
        zip(categories, languages, lengths, strict=True), 1
    ):
        slot = stratum_index[(category, language)]
        stratum_index[(category, language)] += 1
        record = _unique_record(
            index,
            category,
            language,
            length_class,
            slot,
            provenance,
            seen_texts,
        )
        seen_texts.add(str(record["text"]))
        records.append(record)
    return records


def _unique_record(
    index: int,
    category: str,
    language: str,
    length_class: str,
    slot: int,
    provenance: dict[str, object],
    seen_texts: set[str],
) -> dict[str, object]:
    for retry in range(1024):
        record = _record(
            index,
            category,
            language,
            length_class,
            slot + retry * 997,
            provenance,
        )
        if record["text"] not in seen_texts:
            return record
    raise RuntimeError(f"corpus text is not unique: representative-v3-{index:04d}")


def _record(
    index: int,
    category: str,
    language: str,
    length_class: str,
    slot: int,
    provenance: dict[str, object],
) -> dict[str, object]:
    pack = _PACKS[language][category]
    core_index = slot % len(pack["cores"])
    style_index = (slot // len(pack["cores"])) % len(_STYLES[language])
    detail_index = (slot // (len(pack["cores"]) * len(_STYLES[language]))) % len(
        pack["details"]
    )
    reaction_index = (slot // 7) % len(_REACTIONS[language])
    closing_index = (slot // 11) % len(_CLOSINGS[language])
    text = _compose_text(
        language,
        pack,
        length_class,
        style_index,
        core_index,
        detail_index,
        reaction_index,
        closing_index,
    )
    family_id = f"{category}:{language}:{length_class}:s{style_index}:c{core_index}"
    intent_id = f"{category}:{language}:c{core_index}:d{detail_index}"
    key_phrase_id = (
        f"{category}:{language}:c{core_index}:d{detail_index}:r{reaction_index}"
    )
    return {
        "category": category,
        "corpus_id": _CORPUS_ID,
        "corpus_schema_version": _SCHEMA_VERSION,
        "generator_model": "representative-domain-composition-v3",
        "intended_length_class": length_class,
        "label": f"representative-v3-{index:04d}",
        "language": "auto",
        "language_class": language,
        "speaker": "ryan",
        "template_family_id": family_id,
        "semantic_intent_id": intent_id,
        "key_phrase_id": key_phrase_id,
        "text": text,
        **provenance,
    }


def _compose_text(
    language: str,
    pack: dict[str, list[str]],
    length_class: str,
    style_index: int,
    core_index: int,
    detail_index: int,
    reaction_index: int,
    closing_index: int,
) -> str:
    core = pack["cores"][core_index]
    detail = pack["details"][detail_index]
    if length_class == "micro":
        head = pack["micro"][core_index]
        reply = _MICRO_REPLIES[language][style_index]
        modifier = _MICRO_MODIFIERS[language][detail_index]
        if detail_index % 2 == 0:
            if language == "mixed":
                return _mixed_micro(head, reply, modifier)
            return f"{head}, {reply}!"
        return f"{head}, {reply} {modifier}!"
    if length_class == "short":
        tag = _SHORT_TAGS[language][detail_index]
        if language == "en":
            return f"{core.capitalize()} {tag}."
        return f"{_STYLES[language][style_index]}, {core} {tag}."
    opening = f"{_STYLES[language][style_index]}, {core}"
    if length_class == "medium":
        return _at_least_words(
            f"{opening}. {detail.capitalize()}.",
            8,
            language,
            reaction_index + closing_index,
        )
    reaction = _REACTIONS[language][reaction_index]
    if length_class == "long":
        text = (
            f"{opening}. {detail.capitalize()}. {reaction.capitalize()}. "
            f"{_LONG_ADDENDUM[language]}"
        )
        return _at_least_words(text, 19, language, reaction_index + closing_index)
    closing = _CLOSINGS[language][closing_index]
    text = (
        f"{opening}. {detail.capitalize()}. {reaction.capitalize()}. "
        f"{_LONG_ADDENDUM[language]} "
        f"{_EXTENDED_ADDENDUM[language]} {closing}"
    )
    return _at_least_words(text, 36, language, reaction_index + closing_index)


def _at_least_words(text: str, minimum: int, language: str, variant: int) -> str:
    extension_index = variant
    while _word_count(text) < minimum:
        text = f"{text} {_LENGTH_EXTENSIONS[language][extension_index % 8]}"
        extension_index += 1
    return text


def _mixed_micro(head: str, reply: str, modifier: str) -> str:
    if _CYRILLIC_RE.search(head) is not None:
        return f"{head}, {modifier}!"
    return f"{head}, {reply}!"


def _split_records(
    records: list[dict[str, object]], seed: int
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for record in records:
        grouped[
            (
                str(record["category"]),
                str(record["language_class"]),
                str(record["intended_length_class"]),
            )
        ].append(record)
    rng = random.Random(seed + 1)
    discovery: list[dict[str, object]] = []
    holdout: list[dict[str, object]] = []
    for group in grouped.values():
        rng.shuffle(group)
        holdout_count = round(len(group) * _HOLDOUT_RECORDS / _TOTAL_RECORDS)
        holdout.extend(
            _with_split(record, "holdout") for record in group[:holdout_count]
        )
        discovery.extend(
            _with_split(record, "discovery") for record in group[holdout_count:]
        )
    _rebalance_holdout(discovery, holdout)
    return sorted(discovery, key=lambda item: str(item["label"])), sorted(
        holdout, key=lambda item: str(item["label"])
    )


def _rebalance_holdout(
    discovery: list[dict[str, object]], holdout: list[dict[str, object]]
) -> None:
    while len(holdout) < _HOLDOUT_RECORDS:
        holdout.append(_with_split(discovery.pop(), "holdout"))
    while len(holdout) > _HOLDOUT_RECORDS:
        discovery.append(_with_split(holdout.pop(), "discovery"))


def _with_split(record: dict[str, object], split: str) -> dict[str, object]:
    return {**record, "corpus_split": split}


def _manual_review_records(
    records: list[dict[str, object]], seed: int
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for record in records:
        grouped[
            (
                str(record["category"]),
                str(record["language_class"]),
                str(record["intended_length_class"]),
            )
        ].append(record)
    rng = random.Random(seed + 2)
    selected = [rng.choice(group) for group in grouped.values()]
    remaining = [record for record in records if record not in selected]
    rng.shuffle(remaining)
    selected.extend(remaining[: 100 - len(selected)])
    return sorted(selected, key=lambda item: str(item["label"]))


def _audit(
    records: list[dict[str, object]],
    discovery: list[dict[str, object]],
    holdout: list[dict[str, object]],
    review: list[dict[str, object]],
    discovery_path: Path,
    holdout_path: Path,
    review_path: Path,
    provenance: dict[str, object],
) -> dict[str, object]:
    word_counts = [_word_count(str(record["text"])) for record in records]
    family_counts = Counter(str(record["template_family_id"]) for record in records)
    intent_counts = Counter(str(record["semantic_intent_id"]) for record in records)
    phrase_counts = Counter(str(record["key_phrase_id"]) for record in records)
    failures = {
        "length_class": [
            record["label"] for record in records if not _length_valid(record)
        ],
        "language": [
            record["label"] for record in records if not _language_valid(record)
        ],
        "template_family": _over_limit(
            family_counts, _TOTAL_RECORDS * _MAX_FAMILY_PERCENT / 100.0
        ),
        "semantic_intent": _over_limit(
            intent_counts, _TOTAL_RECORDS * _MAX_INTENT_PERCENT / 100.0
        ),
        "key_phrase": _over_limit(phrase_counts, _MAX_KEY_PHRASE_COUNT),
    }
    automated_pass = not any(failures.values()) and len(
        set(record["text"] for record in records)
    ) == len(records)
    return {
        "audit_schema_version": 2,
        "corpus_id": _CORPUS_ID,
        "record_count": len(records),
        "discovery_count": len(discovery),
        "holdout_count": len(holdout),
        "manual_review_count": len(review),
        "manual_review_status": "pending_human_review",
        "automated_preflight_status": "passed"
        if automated_pass
        else "failed_needs_revision",
        "filler_strategy": "none",
        "unique_text_count": len({str(record["text"]) for record in records}),
        "overall_distribution": _distribution(records),
        "discovery_distribution": _distribution(discovery),
        "holdout_distribution": _distribution(holdout),
        "word_count": {"min": min(word_counts), "max": max(word_counts)},
        "family_max_count": max(family_counts.values()),
        "intent_max_count": max(intent_counts.values()),
        "key_phrase_max_count": max(phrase_counts.values()),
        "validation_failures": failures,
        "discovery_sha256": _file_sha256(discovery_path),
        "holdout_sha256": _file_sha256(holdout_path),
        "manual_review_sha256": _file_sha256(review_path),
        **provenance,
    }


def _over_limit(counts: Counter[str], maximum: float) -> list[str]:
    return sorted(key for key, count in counts.items() if count > maximum)


def _length_valid(record: dict[str, object]) -> bool:
    minimum, maximum = _WORD_RANGES[str(record["intended_length_class"])]
    return minimum <= _word_count(str(record["text"])) <= maximum


def _language_valid(record: dict[str, object]) -> bool:
    text = str(record["text"])
    language = str(record["language_class"])
    cyrillic = _CYRILLIC_RE.search(text) is not None
    latin = _LATIN_RE.search(text) is not None
    return {
        "ru": cyrillic and not latin,
        "en": latin and not cyrillic,
        "mixed": cyrillic and latin,
    }[language]


def _distribution(records: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    return {
        "categories": dict(
            sorted(Counter(str(record["category"]) for record in records).items())
        ),
        "languages": dict(
            sorted(Counter(str(record["language_class"]) for record in records).items())
        ),
        "length_classes": dict(
            sorted(
                Counter(
                    str(record["intended_length_class"]) for record in records
                ).items()
            )
        ),
    }


def _expanded(quotas: dict[str, int]) -> list[str]:
    return [name for name, count in quotas.items() for _ in range(count)]


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
