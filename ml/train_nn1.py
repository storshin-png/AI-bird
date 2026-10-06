"""
Обучение NN1 — бинарный классификатор bird / no_bird.
Архитектура: компактная DS-CNN (Depthwise Separable CNN) для Edge.
Вход: (batch, 1, 128, ~218) — log-mel спектрограмма.
Выход: 2 класса (bird / no_bird).
Метрика: F1, precision, recall.
"""
import os
import json
import argparse
import time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from pathlib import Path
from sklearn.metrics import f1_score, precision_score, recall_score, accuracy_score


# ============================================================
# АРХИТЕКТУРА: компактная DS-CNN для Edge
# ============================================================
class DSConvBlock(nn.Module):
    """Depthwise Separable Convolution Block."""
    def __init__(self, in_ch, out_ch, kernel_size=3, stride=1, padding=1):
        super().__init__()
        self.depthwise = nn.Conv2d(in_ch, in_ch, kernel_size, stride, padding, groups=in_ch, bias=False)
        self.bn1 = nn.BatchNorm2d(in_ch)
        self.pointwise = nn.Conv2d(in_ch, out_ch, 1, bias=False)
        self.bn2 = nn.BatchNorm2d(out_ch)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.relu(self.bn1(self.depthwise(x)))
        x = self.relu(self.bn2(self.pointwise(x)))
        return x


class NN1_DS_CNN(nn.Module):
    """
    Компактная DS-CNN для детекции bird/no_bird.
    Целевой размер: ≤ 500 KB после INT8-квантования.
    """
    def __init__(self, num_classes=2):
        super().__init__()
        # Вход: (1, 128, ~218)
        self.features = nn.Sequential(
            nn.Conv2d(1, 32, 3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            DSConvBlock(32, 64, stride=2),     # → (64, 32, ~55)
            DSConvBlock(64, 128, stride=2),    # → (128, 16, ~28)
            DSConvBlock(128, 128),             # → (128, 16, ~28)
            DSConvBlock(128, 256, stride=2),   # → (256, 8, ~14)
            DSConvBlock(256, 256),             # → (256, 8, ~14)
        )
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.classifier = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(256, num_classes)
        )

    def forward(self, x):
        x = self.features(x)
        x = self.pool(x)
        x = x.view(x.size(0), -1)
        x = self.classifier(x)
        return x


# ============================================================
# DATALOADER (с SpecAugment для train)
# ============================================================
class BirdSpectrogramDataset(Dataset):
    def __init__(self, manifest_path, spectro_dir, split, augment=False):
        self.df = pd.read_csv(manifest_path)
        self.df = self.df[self.df["split"] == split].reset_index(drop=True)
        self.spectro_dir = Path(spectro_dir)
        self.augment = augment

        if len(self.df) == 0:
            print(f"[WARN] Нет фрагментов в сплите '{split}'")

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        npy_name = row["fragment_id"].replace(".wav", ".npy")
        npy_path = self.spectro_dir / npy_name

        if not npy_path.exists():
            raise FileNotFoundError(f"Спектрограмма не найдена: {npy_path}")

        spectrogram = np.load(npy_path).astype(np.float32)

        # Нормализация per-sample
        std = spectrogram.std()
        if std > 1e-8:
            spectrogram = (spectrogram - spectrogram.mean()) / std
        else:
            spectrogram = spectrogram - spectrogram.mean()

        # SpecAugment для train (2D массив: T, F)
        if self.augment:
            spectrogram = self._spec_augment(spectrogram)

        # Добавляем канал: (1, T, F)
        spectrogram = spectrogram[np.newaxis, ...]

        label = 1 if row["label"] == "bird" else 0
        return torch.tensor(spectrogram), torch.tensor(label, dtype=torch.long)

    @staticmethod
    def _spec_augment(spec, num_time_masks=2, num_freq_masks=2,
                      time_mask_param=15, freq_mask_param=10):
        """SpecAugment для 2D спектрограммы (T, F)."""
        spec = spec.copy()
        T, F = spec.shape  # 2D: (time_frames, n_mels)

        # Time masking
        for _ in range(num_time_masks):
            t = np.random.randint(0, time_mask_param)
            t0 = np.random.randint(0, max(1, T - t))
            spec[t0:t0 + t, :] = 0.0

        # Frequency masking
        for _ in range(num_freq_masks):
            f = np.random.randint(0, freq_mask_param)
            f0 = np.random.randint(0, max(1, F - f))
            spec[:, f0:f0 + f] = 0.0

        return spec

# ============================================================
# МЕТРИКИ
# ============================================================
def compute_metrics(y_true, y_pred):
    return {
        "f1": f1_score(y_true, y_pred, average="binary"),
        "precision": precision_score(y_true, y_pred, average="binary", zero_division=0),
        "recall": recall_score(y_true, y_pred, average="binary", zero_division=0),
        "accuracy": accuracy_score(y_true, y_pred),
    }


# ============================================================
# ОБУЧЕНИЕ
# ============================================================
def train_one_epoch(model, loader, optimizer, criterion, device):
    model.train()
    total_loss = 0.0
    all_y, all_pred = [], []

    for x, y in loader:
        x, y = x.to(device), y.to(device)
        optimizer.zero_grad()
        logits = model(x)
        loss = criterion(logits, y)
        loss.backward()
        optimizer.step()

        total_loss += loss.item() * x.size(0)
        all_y.extend(y.cpu().numpy())
        all_pred.extend(logits.argmax(1).cpu().numpy())

    avg_loss = total_loss / len(loader.dataset)
    metrics = compute_metrics(all_y, all_pred)
    metrics["loss"] = avg_loss
    return metrics


@torch.no_grad()
def validate(model, loader, criterion, device):
    model.eval()
    total_loss = 0.0
    all_y, all_pred = [], []

    if len(loader.dataset) == 0:
        # Возвращаем пустые метрики для пустого сплита
        return {"loss": 0.0, "f1": 0.0, "precision": 0.0, "recall": 0.0, "accuracy": 0.0}

    for x, y in loader:
        x, y = x.to(device), y.to(device)
        logits = model(x)
        loss = criterion(logits, y)
        total_loss += loss.item() * x.size(0)
        all_y.extend(y.cpu().numpy())
        all_pred.extend(logits.argmax(1).cpu().numpy())

    avg_loss = total_loss / len(loader.dataset)
    metrics = compute_metrics(all_y, all_pred)
    metrics["loss"] = avg_loss
    return metrics

def count_parameters(model):
    return sum(p.numel() for p in model.parameters())


def estimate_model_size_kb(model):
    """Оценка размера модели в KB (FP32)."""
    total_bytes = sum(p.numel() * p.element_size() for p in model.parameters())
    return total_bytes / 1024


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Обучение NN1 (bird/no_bird)")
    parser.add_argument("--manifest", required=True, help="Путь к manifest_fragments.csv")
    parser.add_argument("--spectro", required=True, help="Папка со спектрограммами .npy")
    parser.add_argument("--output", required=True, help="Папка для сохранения модели и логов")
    parser.add_argument("--epochs", type=int, default=50, help="Количество эпох")
    parser.add_argument("--batch-size", type=int, default=32, help="Размер батча")
    parser.add_argument("--lr", type=float, default=1e-3, help="Начальный learning rate")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--early-stop-patience", type=int, default=10, help="Patience для early stopping")
    args = parser.parse_args()

    device = torch.device(args.device)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ОБУЧЕНИЕ NN1 — BIRD / NO_BIRD")
    print("=" * 60)
    print(f"  Device: {device}")
    print(f"  Epochs: {args.epochs}")
    print(f"  Batch size: {args.batch_size}")
    print(f"  LR: {args.lr}")

    # --- DataLoader'ы ---
    train_ds = BirdSpectrogramDataset(args.manifest, args.spectro, "train", augment=True)
    val_ds = BirdSpectrogramDataset(args.manifest, args.spectro, "val", augment=False)
    test_ds = BirdSpectrogramDataset(args.manifest, args.spectro, "test", augment=False)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    print(f"\n  Train: {len(train_ds)} | Val: {len(val_ds)} | Test: {len(test_ds)}")

    # --- Модель ---
    model = NN1_DS_CNN(num_classes=2).to(device)
    n_params = count_parameters(model)
    size_kb = estimate_model_size_kb(model)
    print(f"\n  Параметры: {n_params:,} ({size_kb:.1f} KB FP32)")
    print(f"  Целевой размер после INT8: ~{size_kb/4:.1f} KB")

    # --- Optimizer + Scheduler ---
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    criterion = nn.CrossEntropyLoss()

    # --- Цикл обучения ---
    history = []
    best_f1 = -1.0
    patience_counter = 0
    best_model_path = output_dir / "nn1_best.pth"

    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        train_m = train_one_epoch(model, train_loader, optimizer, criterion, device)
        val_m = validate(model, val_loader, criterion, device)
        scheduler.step()

        elapsed = time.time() - t0
        lr_now = optimizer.param_groups[0]["lr"]

        history.append({
            "epoch": epoch,
            "train_loss": train_m["loss"],
            "train_f1": train_m["f1"],
            "val_loss": val_m["loss"],
            "val_f1": val_m["f1"],
            "val_precision": val_m["precision"],
            "val_recall": val_m["recall"],
            "lr": lr_now,
            "time_sec": elapsed,
        })

        print(f"[Epoch {epoch:03d}/{args.epochs}] "
              f"train_loss={train_m['loss']:.4f} train_f1={train_m['f1']:.4f} | "
              f"val_loss={val_m['loss']:.4f} val_f1={val_m['f1']:.4f} "
              f"(P={val_m['precision']:.3f} R={val_m['recall']:.3f}) | "
              f"lr={lr_now:.2e} | {elapsed:.1f}s")

        # Early stopping по val F1
        if val_m["f1"] > best_f1:
            best_f1 = val_m["f1"]
            patience_counter = 0
            torch.save(model.state_dict(), best_model_path)
            print(f"    ✓ Новая лучшая модель (F1={best_f1:.4f})")
        else:
            patience_counter += 1
            if patience_counter >= args.early_stop_patience:
                print(f"\n[EARLY STOP] Нет улучшений {args.early_stop_patience} эпох")
                break

    # --- Финальный тест на test set ---
    print("\n" + "=" * 60)
    print("ФИНАЛЬНАЯ ПРОВЕРКА НА TEST SET")
    print("=" * 60)

    if not best_model_path.exists():
        print(f"  [WARN] Лучшая модель не сохранена: {best_model_path}")
        print(f"         Причина: F1 ни разу не превысил порог сохранения")
        print(f"         Используем последнюю модель (возможно, она не лучшая)")
        # Сохраняем последнюю модель как fallback
        torch.save(model.state_dict(), best_model_path)
        print(f"         Сохранена последняя модель в {best_model_path}")

    model.load_state_dict(torch.load(best_model_path, weights_only=True))

    if len(test_loader.dataset) == 0:
        print("  [SKIP] Test set пуст — проверка пропущена")
        test_m = {"f1": 0.0, "precision": 0.0, "recall": 0.0, "accuracy": 0.0}
    else:
        test_m = validate(model, test_loader, criterion, device)
        print(f"  Test F1:        {test_m['f1']:.4f}")
        print(f"  Test Precision: {test_m['precision']:.4f}")
        print(f"  Test Recall:    {test_m['recall']:.4f}")
        print(f"  Test Accuracy:  {test_m['accuracy']:.4f}")
    
    # --- Итоговый отчёт ---
    report = {
        "best_val_f1": best_f1,
        "test_f1": test_m["f1"],
        "test_precision": test_m["precision"],
        "test_recall": test_m["recall"],
        "test_accuracy": test_m["accuracy"],
        "parameters": n_params,
        "size_fp32_kb": round(size_kb, 1),
        "size_int8_kb_estimated": round(size_kb / 4, 1),
        "epochs_trained": len(history),
        "target_f1": 0.85,
        "target_size_kb": 500,
        "status": (
            "PASS" if best_f1 >= 0.85 and (size_kb / 4) <= 500 and len(test_loader.dataset) > 0
            else "INCOMPLETE" if len(test_loader.dataset) == 0
            else "NEEDS_IMPROVEMENT"
        ),
    }

    # Сохранение
    pd.DataFrame(history).to_csv(output_dir / "training_log.csv", index=False)
    with open(output_dir / "report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 60)
    print("ИТОГ")
    print("=" * 60)
    for k, v in report.items():
        print(f"  {k}: {v}")

    print(f"\n  Лучшая модель: {best_model_path}")
    print(f"  Лог обучения:  {output_dir / 'training_log.csv'}")
    print(f"  Отчёт:         {output_dir / 'report.json'}")


if __name__ == "__main__":
    main()