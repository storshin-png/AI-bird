# Ключевые требования к инфраструктуре обучения

	4-канальный пайплайн: Все этапы (preprocessing → training → evaluation) должны поддерживать 4-канальный вход. Single-channel baseline делается параллельно для сравнения.
	Hard negatives pipeline: Автоматизированная инжекция направленных шумов (ветер N/E/S/W, насекомые, транспорт) в negative class. Без этого NN1 не достигнет FP ≤10%.
	QAT-цикл: Quantization-Aware Training обязателен. Post-training quantization часто даёт деградацию >5% F1 на 4-канальных данных.
	On-device validation loop: Каждая версия модели тестируется на реальном ESP32-S3 до коммита. Latency ≤300 мс и размер ≤500 KB — hard constraints.
	Версионирование: Модель ↔ версия датасета ↔ метрики. DVC + MLflow обязательны с первого дня.