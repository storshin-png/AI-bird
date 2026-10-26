"""Seed: 50 видов пилота из data/species/species.csv

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25

Снимок data/species/species.csv из main на коммите 3da97ad (PR #13,
19.10.2026, «предварительный список 50 видов пилота»). Строки
вписаны в миграцию, а не читаются из CSV при запуске: миграция должна
давать один и тот же результат, даже если файл потом поменяют.
Изменения списка — новой миграцией.

ВНИМАНИЕ для ревью: в doc_v2/IMPLEMENTATION_PLAN.md §8 строка
«Список 50 видов» на момент миграции стоит как «открыто», а пакет
CLOUD-001 просил не заливать виды до её закрытия. Загрузка добавлена
по решению Lead Backend; принять или вернуть — решение CEO.
red_book_flag = false у всех 50 видов — подтверждает орнитолог.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# (scientific_name, common_name_ru, red_book_flag, in_pilot_50)
SPECIES = (
    ('Parus major', 'Большая синица', False, True),
    ('Cyanistes caeruleus', 'Обыкновенная лазоревка', False, True),
    ('Lophophanes cristatus', 'Хохлатая синица', False, True),
    ('Periparus ater', 'Московка', False, True),
    ('Aegithalos caudatus', 'Длиннохвостая синица', False, True),
    ('Sitta europaea', 'Обыкновенный поползень', False, True),
    ('Certhia familiaris', 'Обыкновенная пищуха', False, True),
    ('Turdus philomelos', 'Певчий дрозд', False, True),
    ('Turdus merula', 'Черный дрозд', False, True),
    ('Turdus pilaris', 'Дрозд-рябинник', False, True),
    ('Turdus iliacus', 'Дрозд-белобровик', False, True),
    ('Lanius collurio', 'Обыкновенный жулан', False, True),
    ('Erithacus rubecula', 'Зарянка', False, True),
    ('Luscinia svecica', 'Варакушка', False, True),
    ('Luscinia luscinia', 'Обыкновенный соловей', False, True),
    ('Phoenicurus ochruros', 'Горихвостка-чернушка', False, True),
    ('Phoenicurus phoenicurus', 'Садовая горихвостка', False, True),
    ('Saxicola rubetra', 'Луговой чекан', False, True),
    ('Oenanthe oenanthe', 'Обыкновенная каменка', False, True),
    ('Fringilla coelebs', 'Зяблик', False, True),
    ('Fringilla montifringilla', 'Вьюрок', False, True),
    ('Chloris chloris', 'Обыкновенная зеленушка', False, True),
    ('Carduelis carduelis', 'Черноголовый щегол', False, True),
    ('Spinus spinus', 'Чиж', False, True),
    ('Acanthis flammea', 'Обыкновенная чечётка', False, True),
    ('Pyrrhula pyrrhula', 'Обыкновенный снегирь', False, True),
    ('Coccothraustes coccothraustes', 'Обыкновенный дубонос', False, True),
    ('Carpodacus erythrinus', 'Обыкновенная чечевица', False, True),
    ('Passer montanus', 'Полевой воробей', False, True),
    ('Passer domesticus', 'Домовый воробей', False, True),
    ('Sturnus vulgaris', 'Обыкновенный скворец', False, True),
    ('Turdus viscivorus', 'Деряба', False, True),
    ('Oriolus oriolus', 'Иволга', False, True),
    ('Garrulus glandarius', 'Сойка', False, True),
    ('Pica pica', 'Сорока', False, True),
    ('Nucifraga caryocatactes', 'Кедровка', False, True),
    ('Corvus frugilegus', 'Грач', False, True),
    ('Corvus cornix', 'Серая ворона', False, True),
    ('Corvus corax', 'Ворон', False, True),
    ('Plectrophenax nivalis', 'Пуночка', False, True),
    ('Troglodytes troglodytes', 'Крапивник', False, True),
    ('Prunella modularis', 'Лесная завирушка', False, True),
    ('Locustella fluviatilis', 'Речной сверчок', False, True),
    ('Acrocephalus dumetorum', 'Садовая камышевка', False, True),
    ('Acrocephalus palustris', 'Болотная камышевка', False, True),
    ('Acrocephalus schoenobaenus', 'Камышевка-барсучок', False, True),
    ('Phylloscopus trochilus', 'Пеночка-весничка', False, True),
    ('Phylloscopus collybita', 'Пеночка-теньковка', False, True),
    ('Phylloscopus trochiloides', 'Зеленая пеночка', False, True),
    ('Sylvia atricapilla', 'Славка-черноголовка', False, True),
)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _bool(value: bool) -> str:
    return "true" if value else "false"


def upgrade() -> None:
    values = ",\n".join(
        f"({_quote(name)}, {_quote(ru)}, {_bool(red)}, {_bool(pilot)})"
        for name, ru, red, pilot in SPECIES
    )
    op.execute(
        "INSERT INTO species (scientific_name, common_name_ru, red_book_flag, in_pilot_50) "
        f"VALUES\n{values}\n"
        "ON CONFLICT (scientific_name) DO NOTHING"
    )


def downgrade() -> None:
    names = ", ".join(_quote(name) for name, *_ in SPECIES)
    op.execute(f"DELETE FROM species WHERE scientific_name IN ({names})")
