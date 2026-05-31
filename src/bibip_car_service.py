from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from models import Car, CarFullInfo, CarStatus, Model, ModelSaleStats, Sale


BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


class CarService:
    # Каждая запись в файле данных занимает фиксированные 500 символов.
    # Это позволит позже читать и обновлять конкретную строку через seek().
    RECORD_SIZE = 500
    RECORD_LINE_SIZE = RECORD_SIZE + 1  # +1 — символ переноса строки \n.

    def __init__(self, root_directory_path: str) -> None:
        self.root_directory_path = root_directory_path

    def _get_file_path(self, file_name: str) -> Path:
        """Вернуть путь к файлу внутри директории, выделенной под базу данных."""
        return Path(self.root_directory_path) / file_name

    def _prepare_data_line(self, record: BaseModel) -> str:
        """Преобразовать Pydantic-модель в JSON-строку фиксированной длины."""
        json_data = record.model_dump_json()

        if len(json_data) > self.RECORD_SIZE:
            raise ValueError("Record is too large for fixed-size storage")

        # ljust добивает строку пробелами до RECORD_SIZE символов.
        # Символ переноса добавляем отдельно, поэтому длина строки = 501.
        return json_data.ljust(self.RECORD_SIZE) + "\n"

    def _write_data_record(self, data_file_name: str, record: BaseModel) -> int:
        """Записать объект в файл данных и вернуть номер добавленной строки."""
        data_file_path = self._get_file_path(data_file_name)

        # Если файла ещё нет, новая запись будет первой строкой с номером 0.
        # Если файл уже есть, номер новой строки равен количеству строк в файле.
        if data_file_path.exists():
            with data_file_path.open("r", encoding="utf-8") as file:
                line_number = sum(1 for _ in file)
        else:
            line_number = 0

        with data_file_path.open("a", encoding="utf-8") as file:
            file.write(self._prepare_data_line(record))

        return line_number

    def _read_index(self, index_file_name: str) -> list[list[str]]:
        """Прочитать индексный файл в память."""
        index_file_path = self._get_file_path(index_file_name)

        if not index_file_path.exists():
            return []

        # Формат строки индекса: ключ;номер_строки.
        with index_file_path.open("r", encoding="utf-8") as file:
            return [line.strip().split(";") for line in file if line.strip()]

    def _find_line_number_by_key(self, index_file_name: str, key: str) -> int | None:
        """Найти номер строки в файле данных по ключу из индекса."""
        for record_key, record_line_number in self._read_index(index_file_name):
            if record_key == key:
                return int(record_line_number)

        return None

    def _read_data_record(
        self,
        data_file_name: str,
        line_number: int,
        model_class: type[BaseModelT],
    ) -> BaseModelT:
        """Прочитать запись из файла данных по номеру строки."""
        data_file_path = self._get_file_path(data_file_name)

        with data_file_path.open("r", encoding="utf-8") as file:
            file.seek(line_number * self.RECORD_LINE_SIZE)
            raw_data = file.read(self.RECORD_SIZE).rstrip()

        # В файле хранится JSON фиксированной длины, добитый пробелами справа.
        # После rstrip() остаётся чистый JSON, который Pydantic превращает обратно в модель.
        return model_class.model_validate_json(raw_data)

    def _read_all_data_records(
        self,
        data_file_name: str,
        model_class: type[BaseModelT],
    ) -> list[BaseModelT]:
        """Прочитать все актуальные записи из файла данных."""
        data_file_path = self._get_file_path(data_file_name)

        if not data_file_path.exists():
            return []

        records = []
        with data_file_path.open("r", encoding="utf-8") as file:
            for line in file:
                raw_data = line.rstrip()
                if raw_data:
                    records.append(model_class.model_validate_json(raw_data))

        return records

    def _write_data_records(
        self,
        data_file_name: str,
        records: list[BaseModel],
    ) -> None:
        """Полностью перезаписать файл данных списком записей."""
        data_file_path = self._get_file_path(data_file_name)

        with data_file_path.open("w", encoding="utf-8") as file:
            for record in records:
                file.write(self._prepare_data_line(record))

    def _rewrite_data_record(
        self,
        data_file_name: str,
        line_number: int,
        record: BaseModel,
    ) -> None:
        """Перезаписать существующую запись в файле данных по номеру строки."""
        data_file_path = self._get_file_path(data_file_name)

        # Режим r+ нужен, чтобы читать и писать в уже существующий файл без очистки содержимого.
        with data_file_path.open("r+", encoding="utf-8") as file:
            file.seek(line_number * self.RECORD_LINE_SIZE)
            file.write(self._prepare_data_line(record))

    def _add_index_record(self, index_file_name: str, key: str, line_number: int) -> None:
        """Добавить запись в индекс и сохранить индекс отсортированным по ключу."""
        index_file_path = self._get_file_path(index_file_name)

        # Индекс маленький по сравнению с файлом данных, поэтому его можно читать целиком в память.
        index_records = self._read_index(index_file_name)

        index_records.append([key, str(line_number)])
        index_records.sort(key=lambda record: record[0])

        with index_file_path.open("w", encoding="utf-8") as file:
            for record_key, record_line_number in index_records:
                file.write(f"{record_key};{record_line_number}\n")

    def _write_index_records(
        self,
        index_file_name: str,
        index_records: list[list[str]],
    ) -> None:
        """Полностью перезаписать индексный файл отсортированными записями."""
        index_file_path = self._get_file_path(index_file_name)
        index_records.sort(key=lambda record: record[0])

        with index_file_path.open("w", encoding="utf-8") as file:
            for record_key, record_line_number in index_records:
                file.write(f"{record_key};{record_line_number}\n")

    # Задание 1. Сохранение автомобилей и моделей
    def add_model(self, model: Model) -> Model:
        """Добавить модель автомобиля в файл данных и индекс по model.id."""
        line_number = self._write_data_record("models.txt", model)
        self._add_index_record("models_index.txt", model.index(), line_number)
        return model

    # Задание 1. Сохранение автомобилей и моделей
    def add_car(self, car: Car) -> Car:
        """Добавить автомобиль в файл данных и индекс по VIN."""
        line_number = self._write_data_record("cars.txt", car)
        self._add_index_record("cars_index.txt", car.index(), line_number)
        return car

    # Задание 2. Сохранение продаж.
    def sell_car(self, sale: Sale) -> Car:
        """Сохранить продажу и изменить статус проданного автомобиля на sold."""
        sale_line_number = self._write_data_record("sales.txt", sale)
        self._add_index_record("sales_index.txt", sale.index(), sale_line_number)

        car_line_number = self._find_line_number_by_key("cars_index.txt", sale.car_vin)
        if car_line_number is None:
            raise ValueError(f"Car with VIN {sale.car_vin} was not found")

        car = self._read_data_record("cars.txt", car_line_number, Car)
        updated_car = car.model_copy(update={"status": CarStatus.sold})

        # VIN не меняется, поэтому индекс cars_index.txt остаётся корректным.
        # Перезаписываем только строку автомобиля в файле cars.txt.
        self._rewrite_data_record("cars.txt", car_line_number, updated_car)
        return updated_car

    # Задание 3. Доступные к продаже
    def get_cars(self, status: CarStatus) -> list[Car]:
        """Вернуть автомобили с указанным статусом в порядке хранения в файле."""
        cars = self._read_all_data_records("cars.txt", Car)
        return [car for car in cars if car.status == status]

    # Задание 4. Детальная информация
    def get_car_info(self, vin: str) -> CarFullInfo | None:
        """Собрать детальную информацию об автомобиле по VIN."""
        car_line_number = self._find_line_number_by_key("cars_index.txt", vin)
        if car_line_number is None:
            return None

        car = self._read_data_record("cars.txt", car_line_number, Car)

        model_line_number = self._find_line_number_by_key("models_index.txt", str(car.model))
        if model_line_number is None:
            raise ValueError(f"Model with id {car.model} was not found")

        model = self._read_data_record("models.txt", model_line_number, Model)

        sales_date = None
        sales_cost = None

        # Продажу ищем только для машин со статусом sold.
        # Для остальных статусов продажи быть не должно, поэтому поля остаются None.
        if car.status == CarStatus.sold:
            sale_line_number = self._find_line_number_by_key("sales_index.txt", car.vin)
            if sale_line_number is not None:
                sale = self._read_data_record("sales.txt", sale_line_number, Sale)
                sales_date = sale.sales_date
                sales_cost = sale.cost

        return CarFullInfo(
            vin=car.vin,
            car_model_name=model.name,
            car_model_brand=model.brand,
            price=car.price,
            date_start=car.date_start,
            status=car.status,
            sales_date=sales_date,
            sales_cost=sales_cost,
        )

    # Задание 5. Обновление ключевого поля
    def update_vin(self, vin: str, new_vin: str) -> Car:
        """Обновить VIN автомобиля и перестроить индекс по VIN."""
        car_line_number = self._find_line_number_by_key("cars_index.txt", vin)
        if car_line_number is None:
            raise ValueError(f"Car with VIN {vin} was not found")

        car = self._read_data_record("cars.txt", car_line_number, Car)
        updated_car = car.model_copy(update={"vin": new_vin})
        self._rewrite_data_record("cars.txt", car_line_number, updated_car)

        # VIN — ключевое поле для cars_index.txt, поэтому после изменения VIN
        # необходимо заменить ключ в индексе и заново отсортировать индекс.
        index_records = self._read_index("cars_index.txt")
        for index_record in index_records:
            if index_record[0] == vin:
                index_record[0] = new_vin
                break

        self._write_index_records("cars_index.txt", index_records)
        return updated_car

    # Задание 6. Удаление продажи
    def revert_sale(self, sales_number: str) -> Car:
        """Удалить продажу и вернуть автомобиль в статус available."""
        sales = self._read_all_data_records("sales.txt", Sale)
        sale_to_delete = next(
            (sale for sale in sales if sale.sales_number == sales_number),
            None,
        )

        if sale_to_delete is None:
            raise ValueError(f"Sale with number {sales_number} was not found")

        actual_sales = [sale for sale in sales if sale.sales_number != sales_number]
        self._write_data_records("sales.txt", actual_sales)

        # После удаления продажи перестраиваем индекс продаж по оставшимся строкам.
        sales_index_records = [
            [sale.index(), str(line_number)]
            for line_number, sale in enumerate(actual_sales)
        ]
        self._write_index_records("sales_index.txt", sales_index_records)

        car_line_number = self._find_line_number_by_key(
            "cars_index.txt",
            sale_to_delete.car_vin,
        )
        if car_line_number is None:
            raise ValueError(f"Car with VIN {sale_to_delete.car_vin} was not found")

        car = self._read_data_record("cars.txt", car_line_number, Car)
        updated_car = car.model_copy(update={"status": CarStatus.available})
        self._rewrite_data_record("cars.txt", car_line_number, updated_car)

        return updated_car

    # Задание 7. Самые продаваемые модели
    def top_models_by_sales(self) -> list[ModelSaleStats]:
        """Вернуть топ-3 модели по количеству продаж."""
        sales = self._read_all_data_records("sales.txt", Sale)
        model_sales_stats = {}

        for sale in sales:
            car_line_number = self._find_line_number_by_key("cars_index.txt", sale.car_vin)
            if car_line_number is None:
                raise ValueError(f"Car with VIN {sale.car_vin} was not found")

            car = self._read_data_record("cars.txt", car_line_number, Car)
            stats = model_sales_stats.setdefault(
                car.model,
                {"sales_number": 0, "max_price": car.price},
            )
            stats["sales_number"] += 1
            stats["max_price"] = max(stats["max_price"], car.price)

        sorted_model_stats = sorted(
            model_sales_stats.items(),
            key=lambda item: (item[1]["sales_number"], item[1]["max_price"]),
            reverse=True,
        )

        result = []
        for model_id, stats in sorted_model_stats[:3]:
            model_line_number = self._find_line_number_by_key(
                "models_index.txt",
                str(model_id),
            )
            if model_line_number is None:
                raise ValueError(f"Model with id {model_id} was not found")

            model = self._read_data_record("models.txt", model_line_number, Model)
            result.append(
                ModelSaleStats(
                    car_model_name=model.name,
                    brand=model.brand,
                    sales_number=stats["sales_number"],
                )
            )

        return result
