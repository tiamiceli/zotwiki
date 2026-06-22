---
zotwiki: 2
title: A Typology of Data Anomalies
created: 2026-06-19
updated: 2026-06-19
citekeys:
  - foorthuisTypologyDataAnomalies2018
zotero_keys:
  - EXKYFB7K
tags:
  - zotwiki
---

# A Typology of Data Anomalies

A Typology of Data Anomalies is a 2018 conference paper by Ralph Foorthuis that proposes a general, tangible classification of the kinds of anomalies (outliers, deviants, novelties) that can occur in datasets. Motivated by the criticism that existing conceptualizations are either too specific (e.g. time-series or regression-specific) or too abstract to be useful, the typology organizes anomalies along two fundamental dimensions of data: the types of data involved (continuous, categorical, or mixed) and the cardinality of the relationship among the attributes responsible for the deviance (univariate or multivariate). Crossing these two dimensions yields six basic anomaly types, from the simple extreme value anomaly to the multidimensional mixed data anomaly. Beyond providing clear definitions, the typology is intended as a functional evaluation framework that lets researchers state which anomaly types a given anomaly detection algorithm can detect, and as an analytical tool for relating anomaly types from other typologies.

## Definition and purpose of anomaly detection

An anomaly is a case that is in some way unusual and does not fit the general patterns of a dataset; such cases are also called outliers, novelties, or deviant observations. Anomaly detection (AD) is the process of analyzing a dataset to identify these deviant cases, and it supports a wide range of goals including fraud detection, data quality analysis, security scanning, process and system monitoring, and data cleansing prior to model training. The paper argues that a clear understanding of anomaly types is needed both to make analytical results interpretable in the face of 'black box' criticism and because the no free lunch theorem implies that no single algorithm detects every type of anomaly.

## Related typologies

The literature already distinguishes several kinds of anomalies, but each existing scheme is either too abstract or too narrow. Some work separates weak outliers (statistical noise) from strong outliers (true anomalies from a different generating mechanism). A widely cited general typology distinguishes point, contextual, and collective anomalies. More specific typologies arise in time-series analysis (additive, transitory change, level shift, and innovational outliers) and in regression analysis (outliers, high-leverage points, and influential points). Foorthuis positions these as either too general to be concrete or too special-purpose to be broadly applicable.

## The two dimensions

The typology distinguishes anomaly types using two dimensions, each capturing a fundamental aspect of the nature of data. The first dimension is the type of data involved in the anomalous behavior: continuous (numeric variables), categorical (codes or class values), or mixed (at least one of each). The second dimension is the cardinality of relationship, describing whether the deviance lies in individual attributes analyzed separately (univariate) or in the joint relationships among attributes that must be analyzed together (multivariate).

## The six anomaly types

Crossing the two dimensions yields six basic types. Type I, the extreme value anomaly, has an extreme or rare value on one or more individual numerical attributes. Type II, the rare class anomaly, has an uncommon class value on one or more categorical variables. Type III, the simple mixed data anomaly, is simultaneously a Type I and a Type II anomaly. Type IV, the multidimensional numerical anomaly, deviates in the combination of several continuous attributes without being extreme on any single one. Type V, the multidimensional rare class anomaly, is a rare combination of class values. Type VI, the multidimensional mixed data anomaly, has a class or combination of classes that is rare only within its local numerical neighborhood.

## Contextual anomalies and dependent data

Foorthuis treats so-called contextual or conditional anomalies as a special case of the multidimensional numerical anomaly in which the contextual attributes (such as time or location) are denoted explicitly; this explicit denotation is permitted but not required. The multivariate types also extend naturally to dependent data, where an additional attribute such as time is needed to link related cases, allowing deviant sequences or phase patterns to be recognized as anomalies.

## Claims

- An anomaly is defined as a case that is in some way unusual and does not appear to fit the general patterns present in a dataset. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] Anomalies are cases that are in some way unusual and do not appear to fit the general patterns present in the dataset
- Anomaly detection is the process of analyzing a dataset to identify deviant cases, and it serves goals such as fraud detection, data quality analysis, security scanning, monitoring, and data cleansing. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] Anomaly detection (AD) is the process of analyzing the dataset to identify these deviant cases.
  > [@foorthuisTypologyDataAnomalies2018] Anomaly detection can be used for various goals, such as fraud detection, data quality analysis, security scanning, process and system monitoring, and data cleansing prior to training statistical models
- The no free lunch theorem holds for anomaly detection, so no single algorithm performs best across all problem domains and individual algorithms cannot detect all anomaly types. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] the no free lunch theorem, which posits that no single algorithm will show superior performance in all problem domains, also holds for anomaly detection
- Part of the motivation for the typology is the criticism of opaque, 'black box' analytics methods that may produce unfair outcomes and lack interpretability. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] with the recent criticism on ‘opaque’ and ‘black box’ analytics methods that may result in unfair outcomes
- The typology distinguishes anomaly types using two dimensions, each describing a fundamental aspect of the nature of data: the types of data involved and the cardinality of the relationship among attributes. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] The first dimension represents the types of data involved in describing the behavior of the cases.
  > [@foorthuisTypologyDataAnomalies2018] The second dimension is the cardinality of relationship and represents how the various attributes relate to each other when describing anomalous behavior.
  > [@foorthuisTypologyDataAnomalies2018] The typology uses two dimensions, each of which describes a fundamental aspect of the nature of data, to distinguish between anomaly types.
- The data-type dimension partitions attributes into continuous (numeric), categorical (codes or class values), and mixed (both continuous and categorical). [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] Categorical: The variables that capture the anomalous behavior all represent codes or class values.
  > [@foorthuisTypologyDataAnomalies2018] Continuous: The variables that capture the anomalous behavior are all numeric in nature.
  > [@foorthuisTypologyDataAnomalies2018] Mixed: The variables that capture the anomalous behavior are both continuous and categorical in nature.
- The cardinality-of-relationship dimension separates univariate anomalies, whose attributes can be analyzed independently, from multivariate anomalies, whose deviance lies in the relationships between variables. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] Multivariate: The deviant behavior of the anomaly lies in the relationships between its variables.
  > [@foorthuisTypologyDataAnomalies2018] Univariate: Except for being part of the same set, no relationship between the variables exists to which the anomalous behavior of the deviant case can be attributed.
- Type I, the extreme value anomaly, is a case with an extremely high, low, or otherwise rare value on one or more individual numerical attributes. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] I. Extreme value anomaly: A case with an extremely high, low or otherwise rare value for one or multiple individual numerical attributes
- Type II, the rare class anomaly, is a case with an uncommon class value on one or more categorical variables. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] II. Rare class anomaly: A case with an uncommon class value for one or multiple categorical variables.
- Type III, the simple mixed data anomaly, is a case that is simultaneously a Type I and a Type II anomaly, having at least one extreme value and one rare class. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] III. Simple mixed data anomaly: A case that is both a Type I and Type II anomaly, i.e. with at least one extreme value and one rare class.
- Type IV, the multidimensional numerical anomaly, deviates in the combination of multiple continuous attributes without being extreme on any single attribute. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] IV. Multidimensional numerical anomaly: A case that does not conform to the general patterns when the relationship between multiple continuous attributes is taken into account, but which does not have extreme values for any of the individual attributes that partake in this relationship.
- Type V, the multidimensional rare class anomaly, is a case with a rare combination of class values. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] V. Multidimensional rare class anomaly: A case with a rare combination of class values.
- Type VI, the multidimensional mixed data anomaly, is a case whose class or class combination is not rare overall but is rare within its local pattern or numerical neighborhood. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] VI. Multidimensional mixed data anomaly: A case with a class or a combination of classes that in itself is not rare in the dataset as a whole, but is only rare in its local pattern or neighborhood (numerical area).
- Contextual or conditional anomalies are treated as a special case of the multidimensional numerical anomaly in which contextual attributes are explicitly denoted. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] So-called ‘contextual’ [13] or ‘conditional’ [14] anomalies should be seen as a special case of a multidimensional numerical anomaly.
- Prior work distinguishes a weak outlier, attributable to statistical variation, from a strong outlier generated by a different mechanism than the normal cases. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] a distinction is made between a weak outlier (noise that can be attributed to the statistical variation of a random variable) and a strong outlier (a true anomaly that may be generated by a mechanism different from the one generating the normal cases)
- An influential general typology differentiates point, contextual, and collective anomalies, where point anomalies are individually deviant, contextual anomalies are deviant only within an explicit context, and collective anomalies deviate as a related group. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] A contextual anomaly appears normal at first sight, but is deviant when an explicitly mentioned context is taken into account
  > [@foorthuisTypologyDataAnomalies2018] A point anomaly refers to one or several individual cases that are deviant with respect to the rest of the data.
  > [@foorthuisTypologyDataAnomalies2018] a collective outlier refers to a group of data points that belong together and, as a group, deviates from the rest of the data.
- Time-series typologies define more specific within-sequence types such as additive, transitory change, level shift, and innovational outliers. [@foorthuisTypologyDataAnomalies2018]
  > [@foorthuisTypologyDataAnomalies2018] A level shift outlier is a sudden but structural change to a higher or lower value level, whereas an innovational outlier may show shifts in both the trend and the seasonal pattern.
  > [@foorthuisTypologyDataAnomalies2018] An additive outlier in this context is an isolated spike during a short period, whereas a transitory change outlier is a spike that requires some time to disappear.

## Links

- [[Anomaly detection]]
- [[Data mining]]
- [[Data quality]]
- [[Fraud detection]]
- [[Machine learning]]
- [[Outliers]]
- [[Pattern recognition]]
- [[Time series analysis]]

## References

- [@foorthuisTypologyDataAnomalies2018] Ralph Foorthuis (2018). *A Typology of Data Anomalies*. [Zotero](zotero://select/library/items/EXKYFB7K)
