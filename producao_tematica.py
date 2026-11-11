"""Pipeline reproduzível da produção temática de risco de crédito.

Uso: python producao_tematica.py --data dados_credito.csv --output resultados
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as ReportImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import PartialDependenceDisplay, permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.calibration import calibration_curve
import joblib


SEED = 42
TARGET = "marcacao_default"
ID_COLUMN = "cliente"
FEATURES = [
    "tipo_emprego",
    "tempo_conta_bancaria",
    "renda_mensal",
    "qtde_outros_emprestimos_atual",
    "valor_mensal_prestacoes_outros_emprestimos_atual",
    "taxa_uso_credito",
    "consultas_credito_ultimos_6meses",
    "pagamentos_atrasados_ultimos_12meses",
    "valor_emprestimo_solicitado",
    "prazo_emprestimo_solicitado",
    "objetivo_empréstimo_solicitado",
    "existencia_garantia",
]
NUMERIC_FEATURES = [feature for feature in FEATURES if feature not in {
    "tipo_emprego",
    "objetivo_empréstimo_solicitado",
    "existencia_garantia",
}]
CATEGORICAL_FEATURES = [feature for feature in FEATURES if feature not in NUMERIC_FEATURES]
DISPLAY_NAMES = {
    "tipo_emprego": "Tipo de emprego",
    "tempo_conta_bancaria": "Tempo de relacionamento bancário",
    "renda_mensal": "Renda mensal",
    "qtde_outros_emprestimos_atual": "Outros empréstimos",
    "valor_mensal_prestacoes_outros_emprestimos_atual": "Prestações mensais existentes",
    "taxa_uso_credito": "Uso de crédito",
    "consultas_credito_ultimos_6meses": "Consultas de crédito (6 meses)",
    "pagamentos_atrasados_ultimos_12meses": "Atrasos (12 meses)",
    "valor_emprestimo_solicitado": "Valor solicitado",
    "prazo_emprestimo_solicitado": "Prazo solicitado",
    "objetivo_empréstimo_solicitado": "Objetivo do empréstimo",
    "existencia_garantia": "Garantia",
}
COLORS = {
    "navy": "#16324F",
    "teal": "#168C8C",
    "orange": "#E58A2B",
    "red": "#C84C4C",
    "light": "#EEF3F7",
    "gray": "#5D6B78",
}


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def load_and_validate(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    try:
        data = pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        data = pd.read_csv(path, encoding="latin-1")

    required = set(FEATURES + [TARGET, ID_COLUMN])
    missing_columns = sorted(required - set(data.columns))
    if missing_columns:
        raise ValueError(f"Colunas obrigatórias ausentes: {missing_columns}")
    if data.empty:
        raise ValueError("A base não contém registros.")

    data = data.copy()
    initial_rows = len(data)
    duplicate_ids = int(data[ID_COLUMN].duplicated(keep=False).sum())
    target_as_number = pd.to_numeric(data[TARGET], errors="coerce")
    invalid_target = int((target_as_number.isna() | ~target_as_number.isin([0, 1])).sum())
    if invalid_target:
        raise ValueError(f"{invalid_target} valores inválidos na variável-alvo; esperado 0/1.")
    data[TARGET] = target_as_number.astype("int8")

    for column in NUMERIC_FEATURES:
        data[column] = pd.to_numeric(data[column], errors="coerce")
        infinite = np.isinf(data[column].to_numpy(dtype=float, na_value=np.nan))
        if infinite.any():
            data.loc[infinite, column] = np.nan
    for column in CATEGORICAL_FEATURES:
        data[column] = data[column].astype("string").str.strip()
        data[column] = data[column].replace("", pd.NA)

    if data[TARGET].nunique() != 2:
        raise ValueError("A variável-alvo precisa conter as duas classes.")

    profile = {
        "n_rows": int(len(data)),
        "n_columns": int(data.shape[1]),
        "duplicate_id_rows": duplicate_ids,
        "missing_by_column": {
            str(k): int(v) for k, v in data.isna().sum().items() if v > 0
        },
        "target_counts": {
            str(k): int(v) for k, v in data[TARGET].value_counts().sort_index().items()
        },
        "target_rate": float(data[TARGET].mean()),
        "rows_before_validation": int(initial_rows),
        "features_used": FEATURES,
    }
    return data, profile


def make_preprocessor(scale_numeric: bool) -> ColumnTransformer:
    numeric_steps: list[tuple[str, Any]] = [
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
    ]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))
    numeric_pipeline = Pipeline(numeric_steps)
    categorical_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    return ColumnTransformer(
        [
            ("numeric", numeric_pipeline, NUMERIC_FEATURES),
            ("categorical", categorical_pipeline, CATEGORICAL_FEATURES),
        ],
        remainder="drop",
    )


def make_model_searches() -> dict[str, GridSearchCV]:
    folds = StratifiedKFold(n_splits=3, shuffle=True, random_state=SEED)
    logistic = Pipeline(
        [
            ("preprocess", make_preprocessor(scale_numeric=True)),
            ("model", LogisticRegression(max_iter=1500, solver="liblinear", random_state=SEED)),
        ]
    )
    forest = Pipeline(
        [
            ("preprocess", make_preprocessor(scale_numeric=False)),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=180,
                    class_weight=None,
                    random_state=SEED,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    return {
        "Regressão logística": GridSearchCV(
            logistic,
            {"model__C": [0.1, 1.0, 10.0]},
            cv=folds,
            scoring="average_precision",
            n_jobs=-1,
            refit=True,
        ),
        "Random Forest": GridSearchCV(
            forest,
            {
                "model__max_depth": [8, None],
                "model__min_samples_leaf": [10, 30],
                "model__max_features": ["sqrt"],
            },
            cv=folds,
            scoring="average_precision",
            n_jobs=-1,
            refit=True,
        ),
    }


def score_at_threshold(y_true: pd.Series, probabilities: np.ndarray, threshold: float) -> dict[str, float]:
    predicted = (probabilities >= threshold).astype(int)
    return {
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
    }


def evaluate(y_true: pd.Series, probabilities: np.ndarray, threshold: float) -> dict[str, Any]:
    threshold_metrics = score_at_threshold(y_true, probabilities, threshold)
    return {
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "average_precision": float(average_precision_score(y_true, probabilities)),
        "brier": float(brier_score_loss(y_true, probabilities)),
        "threshold": float(threshold),
        **threshold_metrics,
        "confusion_matrix": confusion_matrix(
            y_true, (probabilities >= threshold).astype(int), labels=[0, 1]
        ).tolist(),
    }


def calculate_psi(reference: pd.Series, current: pd.Series, bins: int = 10) -> float:
    """Calcula PSI para variável numérica usando cortes quantílicos da referência."""
    ref = pd.to_numeric(reference, errors="coerce").dropna().to_numpy()
    cur = pd.to_numeric(current, errors="coerce").dropna().to_numpy()
    if not len(ref) or not len(cur):
        return float("nan")
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return float("nan")
    edges[0], edges[-1] = -np.inf, np.inf
    ref_counts = np.histogram(ref, bins=edges)[0].astype(float)
    cur_counts = np.histogram(cur, bins=edges)[0].astype(float)
    ref_pct = np.clip(ref_counts / ref_counts.sum(), 1e-6, None)
    cur_pct = np.clip(cur_counts / cur_counts.sum(), 1e-6, None)
    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def make_figures(
    data: pd.DataFrame,
    y_test: pd.Series,
    probabilities: np.ndarray,
    final_model: Pipeline,
    x_train: pd.DataFrame,
    x_test: pd.DataFrame,
    output: Path,
) -> dict[str, Path]:
    figures: dict[str, Path] = {}
    plt.rcParams.update({"font.size": 9, "axes.titleweight": "bold"})

    target_path = output / "distribuicao_alvo.png"
    fig, ax = plt.subplots(figsize=(6, 3.2))
    counts = data[TARGET].value_counts().reindex([0, 1], fill_value=0)
    bars = ax.bar(["Não default (0)", "Default (1)"], counts.values, color=[COLORS["teal"], COLORS["orange"]])
    ax.set_title("Distribuição da variável-alvo")
    ax.set_ylabel("Registros")
    for bar, count in zip(bars, counts.values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{count:,}".replace(",", "."), ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(target_path, dpi=160)
    plt.close(fig)
    figures["target"] = target_path

    missing_path = output / "valores_ausentes.png"
    missing = data[FEATURES].isna().mean().sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(7, 3.8))
    missing[missing > 0].mul(100).plot.barh(ax=ax, color=COLORS["orange"])
    ax.set_title("Valores ausentes nos atributos usados")
    ax.set_xlabel("% de registros")
    ax.set_ylabel("")
    fig.tight_layout()
    fig.savefig(missing_path, dpi=160)
    plt.close(fig)
    figures["missing"] = missing_path

    roc_path = output / "curva_roc.png"
    fpr, tpr, _ = roc_curve(y_test, probabilities)
    auc_value = roc_auc_score(y_test, probabilities)
    fig, ax = plt.subplots(figsize=(5.4, 3.8))
    ax.plot(fpr, tpr, color=COLORS["teal"], lw=2, label=f"AUC = {auc_value:.3f}")
    ax.plot([0, 1], [0, 1], "--", color="#888888")
    ax.set(xlabel="Taxa de falsos positivos", ylabel="Taxa de verdadeiros positivos", title="Curva ROC — conjunto de teste")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(roc_path, dpi=160)
    plt.close(fig)
    figures["roc"] = roc_path

    calibration_path = output / "calibracao.png"
    frac_positive, mean_predicted = calibration_curve(y_test, probabilities, n_bins=10, strategy="quantile")
    fig, ax = plt.subplots(figsize=(5.4, 3.8))
    ax.plot(mean_predicted, frac_positive, marker="o", color=COLORS["teal"], label="Modelo")
    ax.plot([0, 1], [0, 1], "--", color="#888888", label="Calibração perfeita")
    ax.set(xlabel="PD média prevista", ylabel="Frequência observada de default", title="Calibração — teste")
    ax.legend()
    fig.tight_layout()
    fig.savefig(calibration_path, dpi=160)
    plt.close(fig)
    figures["calibration"] = calibration_path

    importance_path = output / "importancia_permutacao.png"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        importance = permutation_importance(
            final_model,
            x_test,
            y_test,
            scoring="average_precision",
            n_repeats=5,
            random_state=SEED,
            n_jobs=-1,
        )
    importance_frame = pd.DataFrame(
        {
            "feature": FEATURES,
            "mean": importance.importances_mean,
            "std": importance.importances_std,
        }
    ).sort_values("mean", ascending=True)
    importance_frame.to_csv(output / "importancia_permutacao.csv", index=False, encoding="utf-8-sig")
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.barh(
        [DISPLAY_NAMES.get(f, f) for f in importance_frame["feature"]],
        importance_frame["mean"],
        xerr=importance_frame["std"],
        color=COLORS["teal"],
    )
    ax.axvline(0, color="#555555", lw=0.8)
    ax.set_title("Importância por permutação (variação de Average Precision)")
    ax.set_xlabel("Redução média do Average Precision ao embaralhar")
    fig.tight_layout()
    fig.savefig(importance_path, dpi=160)
    plt.close(fig)
    figures["importance"] = importance_path

    top_numeric = [
        feature for feature in importance_frame.sort_values("mean", ascending=False)["feature"]
        if feature in NUMERIC_FEATURES
    ][:3]
    if top_numeric:
        dependence_path = output / "efeito_medio_variaveis.png"
        fig, ax = plt.subplots(nrows=len(top_numeric), ncols=1, figsize=(8, 3.2 * len(top_numeric)))
        axes = np.atleast_1d(ax)
        dependence_data = x_test.copy()
        for feature in top_numeric:
            dependence_data[feature] = dependence_data[feature].astype(float)
        PartialDependenceDisplay.from_estimator(
            final_model,
            dependence_data,
            features=top_numeric,
            kind="average",
            grid_resolution=20,
            ax=axes[:len(top_numeric)],
        )
        for axis, feature in zip(axes, top_numeric):
            axis.set_title(DISPLAY_NAMES.get(feature, feature))
            axis.set_ylabel("PD média estimada")
            axis.set_xlabel(DISPLAY_NAMES.get(feature, feature))
        fig.tight_layout()
        fig.savefig(dependence_path, dpi=160)
        plt.close(fig)
        figures["dependence"] = dependence_path
    return figures


def write_predictions(
    x_test: pd.DataFrame,
    y_test: pd.Series,
    probabilities: np.ndarray,
    threshold: float,
    output: Path,
) -> None:
    scored = pd.DataFrame(
        {
            "cliente": x_test[ID_COLUMN].to_numpy(),
            "default_observado": y_test.to_numpy(),
            "pd_estimada": probabilities,
            "classificacao_no_limiar_050": (probabilities >= threshold).astype(int),
        }
    )
    scored.to_csv(output / "predicoes_teste.csv", index=False, encoding="utf-8-sig")


def make_monitoring_table(
    x_train: pd.DataFrame, x_test: pd.DataFrame, output: Path
) -> pd.DataFrame:
    rows = []
    for feature in NUMERIC_FEATURES:
        rows.append(
            {
                "variavel": feature,
                "psi_referencia_teste": calculate_psi(x_train[feature], x_test[feature]),
                "tipo": "numérica",
            }
        )
    monitor = pd.DataFrame(rows).sort_values("psi_referencia_teste", ascending=False)
    monitor.to_csv(output / "psi_referencia.csv", index=False, encoding="utf-8-sig")
    return monitor


def make_eda_tables(data: pd.DataFrame, output: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    numeric_rows = []
    for feature in NUMERIC_FEATURES:
        values = data[feature]
        numeric_rows.append({
            "variavel": feature,
            "ausentes": int(values.isna().sum()),
            "mediana_sem_default": float(data.loc[data[TARGET] == 0, feature].median()),
            "mediana_default": float(data.loc[data[TARGET] == 1, feature].median()),
        })
    numeric_summary = pd.DataFrame(numeric_rows)
    numeric_summary.to_csv(output / "perfil_numerico.csv", index=False, encoding="utf-8-sig")

    categorical_rows = []
    for feature in CATEGORICAL_FEATURES:
        grouped = data.groupby(feature, dropna=False, observed=True)[TARGET].agg(["count", "mean"])
        for value, row in grouped.iterrows():
            categorical_rows.append({
                "variavel": feature,
                "categoria": "(ausente)" if pd.isna(value) else str(value),
                "registros": int(row["count"]),
                "taxa_default": float(row["mean"]),
            })
    categorical_summary = pd.DataFrame(categorical_rows)
    categorical_summary = categorical_summary[categorical_summary["registros"] >= 100].sort_values(
        "taxa_default", ascending=False
    )
    categorical_summary.to_csv(output / "perfil_categorico.csv", index=False, encoding="utf-8-sig")
    return numeric_summary, categorical_summary


def build_report(
    output: Path,
    profile: dict[str, Any],
    search_results: dict[str, Any],
    metrics: dict[str, Any],
    best_name: str,
    figures: dict[str, Path],
    importance: pd.DataFrame,
    psi: pd.DataFrame,
    numeric_summary: pd.DataFrame,
    categorical_summary: pd.DataFrame,
) -> None:
    pdf_path = output / "relatorio_producao_tematica.pdf"
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitlePT", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=colors.HexColor(COLORS["navy"]), spaceAfter=12))
    styles.add(ParagraphStyle(name="HeadingPT", parent=styles["Heading2"], fontSize=14, leading=17, textColor=colors.HexColor(COLORS["teal"]), spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle(name="BodyPT", parent=styles["BodyText"], fontSize=9, leading=13, alignment=TA_LEFT, spaceAfter=6))
    styles.add(ParagraphStyle(name="SmallPT", parent=styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor(COLORS["gray"])))
    story: list[Any] = []
    story += [
        Paragraph("Modelagem e monitoração de risco de crédito", styles["TitlePT"]),
        Paragraph("Produção temática | Estimativa de probabilidade de default", styles["Heading2"]),
        Paragraph(
            "Objetivo: construir um fluxo analítico reproduzível para estimar a probabilidade de default (PD), "
            "avaliar seu desempenho retrospectivo e propor governança de monitoração para uso contínuo.",
            styles["BodyPT"],
        ),
        Spacer(1, 5 * mm),
        Paragraph("Resumo executivo", styles["HeadingPT"]),
        Paragraph(
            f"A base analisada contém <b>{profile['n_rows']:,}</b> registros e {profile['n_columns']} colunas. "
            f"Foram observados {profile['target_counts'].get('1', 0):,} defaults "
            f"({profile['target_rate']:.2%}). O melhor resultado de validação cruzada foi obtido por "
            f"<b>{best_name}</b>; no teste estratificado, ROC AUC={metrics['roc_auc']:.3f}, "
            f"Average Precision={metrics['average_precision']:.3f} e Brier={metrics['brier']:.4f}. "
            "Este é um estudo retrospectivo, não uma aprovação para decisão automatizada de crédito.",
            styles["BodyPT"],
        ),
        ReportImage(str(figures["target"]), width=150 * mm, height=80 * mm),
        Paragraph("1. Contexto, dados e limitações", styles["HeadingPT"]),
        Paragraph(
            "A base contém 25 mil solicitações e a variável-alvo marcacao_default (0/1). A taxa observada de default "
            f"é {profile['target_rate']:.2%}, evidenciando desbalanceamento. Foram encontrados valores ausentes em "
            f"{len(profile['missing_by_column'])} coluna(s): "
            + ", ".join(f"{k} ({v:,})" for k, v in profile["missing_by_column"].items())
            + ". O identificador cliente foi verificado ("
            + f"{profile['duplicate_id_rows']} linhas em IDs duplicados) e excluído das predições.",
            styles["BodyPT"],
        ),
        Paragraph(
            "Limitações principais: a base não traz data de observação/originação, definição operacional de default, "
            "horizonte da PD, exposição/perda, nem janela de performance; portanto não é possível testar generalização "
            "temporal, estimar LGD/EAD, validar estabilidade real, ou confirmar ausência de variáveis posteriores ao evento. "
            "O split aleatório estratificado pode superestimar desempenho futuro e a amostra não demonstra representatividade "
            "da população de implantação.",
            styles["BodyPT"],
        ),
        ReportImage(str(figures["missing"]), width=155 * mm, height=84 * mm),
        Paragraph("2. Análise e engenharia dos dados", styles["HeadingPT"]),
        Paragraph(
            "O script valida colunas obrigatórias, alvo binário e linhas não vazias; converte campos numéricos com "
            "valores inválidos para ausentes e padroniza categorias textuais. Imputação mediana (numéricas) e moda "
            "(categóricas), indicadores de ausência numérica, escala para regressão logística e one-hot encoding com "
            "categorias inéditas ignoradas são ajustados dentro do pipeline após a separação treino/teste, evitando "
            "vazamento de informação. A semente fixa (42), os splits e o pipeline serializado permitem reprodutibilidade.",
            styles["BodyPT"],
        ),
        Paragraph(
            "Foram usadas variáveis de relacionamento e capacidade/conduta de crédito, emprego, condições da proposta "
            "e garantia. Foram excluídos cliente (identificador), idade, gênero, estado civil, estado e tipo de cidade "
            "por minimização de dados, equidade e redução de proxies geográficos. A seleção é uma decisão inicial de "
            "governança que deve ser validada com Jurídico/Compliance e análise de impacto no contexto real.",
            styles["BodyPT"],
        ),
        Paragraph(
            "Comportamento numérico: medianas observadas por classe (descrição, não efeito causal)",
            styles["HeadingPT"],
        ),
    ]
    numeric_table = [["Atributo", "Ausentes", "Mediana sem default", "Mediana default"]]
    for _, row in numeric_summary.iterrows():
        numeric_table.append([
            DISPLAY_NAMES.get(row["variavel"], row["variavel"]),
            f"{int(row['ausentes']):,}",
            f"{row['mediana_sem_default']:.2f}" if pd.notna(row["mediana_sem_default"]) else "n/d",
            f"{row['mediana_default']:.2f}" if pd.notna(row["mediana_default"]) else "n/d",
        ])
    story.append(make_report_table(numeric_table, [62 * mm, 24 * mm, 45 * mm, 45 * mm]))
    cat_table = [["Atributo", "Categoria", "N", "Taxa default"]]
    for _, row in categorical_summary.head(12).iterrows():
        cat_table.append([
            DISPLAY_NAMES.get(row["variavel"], row["variavel"]),
            row["categoria"],
            f"{int(row['registros']):,}",
            f"{row['taxa_default']:.2%}",
        ])
    story.extend([
        Paragraph(
            "Categorias com maiores taxas observadas entre as que têm ao menos 100 registros; "
            "comparação descritiva sujeita a incerteza amostral.",
            styles["BodyPT"],
        ),
        make_report_table(cat_table, [48 * mm, 62 * mm, 25 * mm, 35 * mm]),
        PageBreak(),
    ])
    story += [
        Paragraph("3. Construção e avaliação do modelo", styles["HeadingPT"]),
        Paragraph(
            "Foram comparadas regressão logística (baseline interpretável) e Random Forest (não linear), com busca "
            "de hiperparâmetros em validação cruzada estratificada de 3 folds no treino. O critério de seleção foi "
            "Average Precision, mais informativo que acurácia em classes desbalanceadas. O teste final foi separado "
            "antes do ajuste (80/20, estratificado, semente 42) e utilizado somente uma vez na avaliação.",
            styles["BodyPT"],
        ),
    ]
    table_data = [["Modelo", "AP médio CV", "Desvio CV", "Hiperparâmetros selecionados"]]
    for name, result in search_results.items():
        params = ", ".join(f"{k.split('__')[-1]}={v}" for k, v in result["best_params"].items())
        table_data.append([name, f"{result['best_score']:.3f}", f"{result['cv_std']:.3f}", params])
    story.append(make_report_table(table_data, [37 * mm, 27 * mm, 23 * mm, 85 * mm]))
    metric_data = [
        ["Métrica (teste)", "Resultado", "Leitura"],
        ["ROC AUC", f"{metrics['roc_auc']:.3f}", "Ordenação global das classes"],
        ["Average Precision", f"{metrics['average_precision']:.3f}", "Precisão-revocação; baseline = prevalência"],
        ["Brier score", f"{metrics['brier']:.4f}", "Erro quadrático das probabilidades (menor é melhor)"],
        ["Precisão / Recall / F1 (0,50)", f"{metrics['precision']:.3f} / {metrics['recall']:.3f} / {metrics['f1']:.3f}", "Limiar ilustrativo, não otimizado para decisão"],
    ]
    story.append(make_report_table(metric_data, [45 * mm, 45 * mm, 82 * mm]))
    story += [
        ReportImage(str(figures["roc"]), width=110 * mm, height=78 * mm),
        ReportImage(str(figures["calibration"]), width=110 * mm, height=78 * mm),
        Paragraph(
            "A PD é uma probabilidade estimada, não uma decisão. O limiar 0,50 foi mantido apenas para reportar "
            "matriz de confusão/precisão/recall; na implantação, o limiar deve resultar de apetite de risco, custos "
            "de erro, capacidade operacional, calibração por horizonte e validação independente. Mesmo sem ponderação "
            "de classe, a calibração deve ser validada; calibração pós-treino (por exemplo, isotônica ou sigmoide) "
            "pode ser avaliada em amostra separada se necessário.",
            styles["BodyPT"],
        ),
        Paragraph("4. Explicabilidade", styles["HeadingPT"]),
        Paragraph(
            "A importância por permutação foi calculada no conjunto de teste, medindo a queda média de Average "
            "Precision ao embaralhar cada atributo. A medida permite priorizar variáveis globalmente, mas não prova "
            "causalidade, pode repartir importância entre atributos correlacionados e não revela sozinha o efeito "
            "individual de cada valor. Para explicação local em produção, registrar PD, versão do modelo, entradas "
            "autorizadas e uma explicação local validada (por exemplo, SHAP) com trilha de auditoria; revisar "
            "explicações e resultados por grupos de forma juridicamente apropriada.",
            styles["BodyPT"],
        ),
        ReportImage(str(figures["importance"]), width=155 * mm, height=100 * mm),
        Paragraph(
            "Os gráficos de dependência parcial abaixo mostram como a PD média estimada varia ao longo dos valores "
            "dos atributos numéricos mais relevantes, mantendo em média os demais atributos da amostra. São efeitos "
            "associativos do modelo e podem ser enganosos quando há forte correlação entre atributos.",
            styles["BodyPT"],
        ),
        ReportImage(str(figures["dependence"]), width=155 * mm, height=min(140, 43 * len(NUMERIC_FEATURES)) * mm),
        Paragraph("5. Estratégia de monitoração contínua", styles["HeadingPT"]),
    ]
    story.append(make_report_table(
        [
            ["Camada", "Métricas / frequência", "Sinal e ação sugerida"],
            ["Qualidade de dados", "Esquema, tipos, ausências, faixa, categorias novas; por lote", "Falha crítica de schema/ausência ou faixa impossível: bloquear lote e investigar"],
            ["Estabilidade", "PSI para PD e atributos; mensal (dados de score semanal)", "PSI &lt;0,10 baixo; 0,10–0,25 alerta; ≥0,25 crítico; investigar causa e impacto"],
            ["Desempenho", "ROC AUC, AP, recall/precisão em limiar vigente, Brier/calibração; mensal após maturação do alvo", "Queda AUC &gt;0,05 ou AP &gt;20% vs baseline, ou quebra do limite de risco: revisão independente"],
            ["Equidade / operação", "Métricas por grupos legalmente permitidos, cobertura, aprovação, reclamações e overrides; mensal/trimestral", "Diferenças persistentes ou dano ao cliente: suspender/mitigar e escalar a governança"],
        ],
        [27 * mm, 67 * mm, 78 * mm],
    ))
    story += [
        Paragraph(
            "PSI de treino versus teste fornecido é somente uma referência ilustrativa do split aleatório, não uma "
            "medição de drift temporal. Na operação, congelar uma população de referência (treino/validação aprovada), "
            "versionar bins e calcular PSI por janela. Garantir amostra mínima e número de defaults antes de interpretar "
            "métricas; acompanhar resultados com atraso de maturação do default. Retreino não deve ser automático: "
            "gatilhos abrem investigação, validação, aprovação e comparação champion/challenger antes de promover versão.",
            styles["BodyPT"],
        ),
    ]
    top_psi = psi.head(5)
    if not top_psi.empty:
        story.append(Paragraph("PSI ilustrativo (treino versus teste, split aleatório)", styles["HeadingPT"]))
        story.append(make_report_table(
            [["Atributo", "PSI"]] + [[DISPLAY_NAMES.get(r["variavel"], r["variavel"]), f"{r['psi_referencia_teste']:.4f}"] for _, r in top_psi.iterrows()],
            [90 * mm, 40 * mm],
        ))
    story += [
        Paragraph("6. Arquitetura operacional proposta", styles["HeadingPT"]),
        Paragraph(
            "<b>Ingestão/contratos:</b> fonte versionada, validação de schema e qualidade; <b>features:</b> transformações "
            "reutilizáveis e versionadas; <b>treino/validação:</b> pipeline, split temporal, tuning, calibração e aprovação; "
            "<b>registro:</b> artefato do modelo, versão de dados/código, hiperparâmetros e métricas em registry e armazenamento "
            "de objetos; <b>serving:</b> batch/API com score, identificador pseudonimizado e explicação; <b>monitoração:</b> "
            "tabelas históricas de qualidade, drift e performance, painel e alertas. Orquestração em DAG (Airflow/Prefect), "
            "CI/CD, controle de acesso, criptografia, retenção e auditoria. Escalar por processamento em lotes, armazenamento "
            "colunar e workers paralelos; preservar reprodutibilidade por imagem/container imutável.",
            styles["BodyPT"],
        ),
        Paragraph("Conclusão e recomendações", styles["HeadingPT"]),
        Paragraph(
            "O fluxo entrega baseline reproduzível, comparação de algoritmos, PD por registro de teste, métricas e artefatos "
            "de explicabilidade/estabilidade. Antes de qualquer uso em decisão: definir default e horizonte; conseguir coorte "
            "temporal e dados de resultado; validar calibração, estabilidade, equidade e impacto econômico; revisar variáveis "
            "e limiar; realizar validação independente, aprovação de governança e plano de contingência. Até então, utilizar "
            "apenas como protótipo analítico, com revisão humana e sem automatizar concessão/recusa.",
            styles["BodyPT"],
        ),
        Spacer(1, 6 * mm),
        Paragraph(
            "Artefatos associados: código-fonte producao_tematica.py, pipeline_serializado.joblib, "
            "metricas.json, predicoes_teste.csv, importancia_permutacao.csv, perfil_numerico.csv, "
            "perfil_categorico.csv e psi_referencia.csv. "
            "A execução registra versão das bibliotecas e parâmetros no arquivo metricas.json.",
            styles["SmallPT"],
        ),
    ]

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor(COLORS["gray"]))
        canvas.drawString(18 * mm, 12 * mm, "Produção temática — risco de crédito | Protótipo retrospectivo")
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Página {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=17 * mm, bottomMargin=20 * mm)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def make_report_table(data: list[list[str]], widths: list[float]) -> Table:
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLORS["navy"])),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CCD5DD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(COLORS["light"])]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def add_slide(prs: Presentation, title: str, bullets: list[str], subtitle: str | None = None) -> Any:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    background = slide.background.fill
    background.solid()
    background.fore_color.rgb = RGBColor(245, 248, 251)
    header = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(0.82))
    header.fill.solid()
    header.fill.fore_color.rgb = RGBColor(22, 50, 79)
    header.line.fill.background()
    title_box = slide.shapes.add_textbox(Inches(0.55), Inches(0.15), Inches(12.1), Inches(0.52))
    title_tf = title_box.text_frame
    title_tf.clear()
    p = title_tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(24)
    p.font.bold = True
    p.font.color.rgb = RGBColor(255, 255, 255)
    if subtitle:
        sub = slide.shapes.add_textbox(Inches(0.7), Inches(1.0), Inches(11.9), Inches(0.5))
        para = sub.text_frame.paragraphs[0]
        para.text = subtitle
        para.font.size = Pt(16)
        para.font.color.rgb = RGBColor(22, 140, 140)
    text_top = 1.65 if subtitle else 1.25
    box = slide.shapes.add_textbox(Inches(0.75), Inches(text_top), Inches(11.8), Inches(5.2))
    tf = box.text_frame
    tf.word_wrap = True
    for index, bullet in enumerate(bullets):
        p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        p.text = bullet
        p.font.size = Pt(21 if len(bullets) < 5 else 18)
        p.font.color.rgb = RGBColor(40, 55, 70)
        p.space_after = Pt(18)
        p.level = 0
    footer = slide.shapes.add_textbox(Inches(0.65), Inches(7.12), Inches(12), Inches(0.22))
    p = footer.text_frame.paragraphs[0]
    p.text = "Produção temática | Risco de crédito — protótipo retrospectivo"
    p.font.size = Pt(9)
    p.font.color.rgb = RGBColor(93, 107, 120)
    return slide


def make_presentation(output: Path, profile: dict[str, Any], best_name: str, metrics: dict[str, Any], top_features: list[str]) -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    add_slide(prs, "Probabilidade de default", [
        "Modelo preditivo e proposta de monitoração contínua",
        "Produção temática | Gestão de risco de crédito",
        "Objetivo: estimar PD com rastreabilidade, governança e evidências.",
    ], "Da preparação dos dados ao acompanhamento do modelo")
    add_slide(prs, "O desafio e a base", [
        f"{profile['n_rows']:,} solicitações | {profile['n_columns']} colunas",
        f"Default observado: {profile['target_rate']:.2%} ({profile['target_counts'].get('1', 0):,} registros)",
        f"Ausências: {sum(profile['missing_by_column'].values()):,} células em {len(profile['missing_by_column'])} variáveis",
        "Sem datas nem horizonte explícito: validação temporal e drift real não são possíveis.",
    ])
    add_slide(prs, "Preparação com governança", [
        "ID cliente removido; dados demográficos e localização excluídos por minimização e risco de proxy.",
        "12 atributos de crédito, relacionamento, emprego e condições da proposta.",
        "Imputação e codificação aprendidas somente no treino; pipeline versionado e reproduzível.",
        "Ausências numéricas registradas por indicadores; categorias novas aceitas no scoring.",
    ])
    add_slide(prs, "Modelos e desenho experimental", [
        "Regressão logística (baseline interpretável) versus Random Forest (não linear).",
        "Split estratificado treino/teste 80/20; busca de parâmetros com CV estratificada de 3 folds.",
        "Average Precision como critério principal diante do desbalanceamento.",
        "PD é probabilidade, não decisão; limiar operacional depende de custo e apetite de risco.",
    ])
    add_slide(prs, "Resultado no teste", [
        f"Selecionado: {best_name}",
        f"ROC AUC {metrics['roc_auc']:.3f} | Average Precision {metrics['average_precision']:.3f}",
        f"Brier {metrics['brier']:.4f} | Precision / Recall no limiar 0,50: {metrics['precision']:.3f} / {metrics['recall']:.3f}",
        "Resultado retrospectivo; não comprova desempenho futuro nem calibração em produção.",
    ])
    add_slide(prs, "Explicabilidade", [
        "Importância por permutação no conjunto de teste: impacto global na Average Precision.",
        "Atributos de maior relevância observada: " + "; ".join(top_features[:4]) + ".",
        "Importância não implica causalidade e pode ser compartilhada por variáveis correlacionadas.",
        "Em produção: explicação local auditável, versão do modelo e análise de resultados por grupos.",
    ])
    add_slide(prs, "Monitoração contínua", [
        "Semanal: schema, completude, faixas, categorias novas e distribuição dos scores.",
        "Mensal: PSI dos atributos/PD; performance após maturação do default (ROC AUC, AP, recall, Brier).",
        "PSI <0,10 baixo; 0,10–0,25 alerta; ≥0,25 crítico — investigar antes de retreinar.",
        "Gatilhos: queda AUC >0,05, AP >20% vs baseline, quebra de calibração ou alertas de equidade.",
    ])
    add_slide(prs, "Arquitetura e recomendações", [
        "DAG: ingestão/qualidade → features → treino/validação → registry → scoring → monitoração.",
        "Guardar métricas, dados de referência, versões e decisões em storage versionado e auditável.",
        "Automatizar alertas; retreino somente após investigação, validação independente e aprovação.",
        "Próximos passos: definir target/horizonte, obter coorte temporal e validar impacto/equidade.",
        "Uso recomendado agora: protótipo analítico, sem decisão automatizada de concessão ou recusa.",
    ])
    prs.save(output / "apresentacao_producao_tematica.pptx")
    make_slides_pdf(output / "apresentacao_producao_tematica.pdf", prs)


def make_slides_pdf(path: Path, prs: Presentation) -> None:
    page_size = landscape((13.333 * 72, 7.5 * 72))
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("SlideTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=30, textColor=colors.white, alignment=TA_LEFT)
    bullet_style = ParagraphStyle("SlideBullet", parent=styles["BodyText"], fontSize=20, leading=28, textColor=colors.HexColor("#283746"), leftIndent=15, firstLineIndent=-12, spaceAfter=18)
    subtitle_style = ParagraphStyle("SlideSubtitle", parent=styles["Heading2"], fontSize=17, leading=21, textColor=colors.HexColor(COLORS["teal"]))
    footer_style = ParagraphStyle("SlideFooter", parent=styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor(COLORS["gray"]))
    elems: list[Any] = []
    for slide in prs.slides:
        texts = [
            line.strip()
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False)
            for line in shape.text.splitlines()
            if line.strip()
        ]
        slide_title = texts[0] if texts else ""
        content = texts[1:-1] if len(texts) > 2 else texts[1:]
        elems.append(Table([[Paragraph(slide_title, title_style)]], colWidths=[page_size[0] - 70], rowHeights=[62], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(COLORS["navy"])),
            ("LEFTPADDING", (0, 0), (-1, -1), 20),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])))
        elems.append(Spacer(1, 24))
        if content and slide_title == "Probabilidade de default":
            elems.append(Paragraph(content[0], subtitle_style))
            elems.append(Spacer(1, 18))
            content = content[1:]
        for line in content:
            if line.startswith("Produção temática |"):
                continue
            elems.append(Paragraph("• " + line, bullet_style))
        elems.append(Spacer(1, 24))
        elems.append(Paragraph("Produção temática | Risco de crédito — protótipo retrospectivo", footer_style))
        elems.append(PageBreak())
    doc = SimpleDocTemplate(str(path), pagesize=page_size, leftMargin=35, rightMargin=35, topMargin=25, bottomMargin=25)
    doc.build(elems[:-1])


def run(data_path: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    data, profile = load_and_validate(data_path)
    logging.info("Base validada: %s linhas, %s colunas.", profile["n_rows"], profile["n_columns"])

    # O identificador é preservado apenas para rastrear a saída, nunca é feature.
    x = data[FEATURES + [ID_COLUMN]].copy()
    y = data[TARGET].copy()
    x_train_full, x_test_full, y_train, y_test = train_test_split(
        x, y, test_size=0.20, stratify=y, random_state=SEED
    )
    x_train = x_train_full[FEATURES].copy()
    x_test = x_test_full[FEATURES].copy()
    searches = make_model_searches()
    fitted: dict[str, GridSearchCV] = {}
    for name, search in searches.items():
        logging.info("Treinando e ajustando %s...", name)
        search.fit(x_train, y_train)
        fitted[name] = search
        logging.info("%s: AP CV=%.4f, parâmetros=%s", name, search.best_score_, search.best_params_)

    best_name, best_search = max(fitted.items(), key=lambda item: item[1].best_score_)
    model: Pipeline = best_search.best_estimator_
    probabilities = model.predict_proba(x_test)[:, 1]
    metrics = evaluate(y_test, probabilities, threshold=0.5)
    search_results = {
        name: {
            "best_score": float(search.best_score_),
            "cv_std": float(search.cv_results_["std_test_score"][search.best_index_]),
            "best_params": search.best_params_,
        }
        for name, search in fitted.items()
    }
    metrics_document = {
        "dataset": profile,
        "random_seed": SEED,
        "split": {"train_rows": len(x_train), "test_rows": len(x_test), "test_size": 0.2, "stratified": True},
        "selection_metric": "average_precision",
        "models_cv": search_results,
        "selected_model": best_name,
        "test_metrics": metrics,
        "warning": "Avaliação retrospectiva aleatória; sem datas, não representa validação temporal.",
        "versions": {
            "python": __import__("platform").python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scikit_learn": __import__("sklearn").__version__,
        },
    }
    (output / "metricas.json").write_text(json.dumps(metrics_document, ensure_ascii=False, indent=2), encoding="utf-8")
    joblib.dump(model, output / "pipeline_serializado.joblib")
    write_predictions(x_test_full, y_test, probabilities, 0.5, output)
    psi = make_monitoring_table(x_train, x_test, output)
    numeric_summary, categorical_summary = make_eda_tables(data, output)
    figures = make_figures(data, y_test, probabilities, model, x_train, x_test, output)
    importance = pd.read_csv(output / "importancia_permutacao.csv")
    build_report(
        output,
        profile,
        search_results,
        metrics,
        best_name,
        figures,
        importance,
        psi,
        numeric_summary,
        categorical_summary,
    )
    top_features = [
        DISPLAY_NAMES.get(feature, feature)
        for feature in importance.sort_values("mean", ascending=False)["feature"].head(5)
    ]
    make_presentation(output, profile, best_name, metrics, top_features)
    logging.info("Concluído. Entregáveis em %s", output.resolve())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa a produção temática de risco de crédito.")
    parser.add_argument("--data", type=Path, default=Path("dados_credito.csv"), help="Caminho para o CSV de entrada.")
    parser.add_argument("--output", type=Path, default=Path("resultados"), help="Diretório de saída.")
    return parser.parse_args()


if __name__ == "__main__":
    setup_logging()
    args = parse_args()
    run(args.data, args.output)
