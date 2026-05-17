
# Valorisation Obligataire Maroc - Valorisation Obligataire Maroc avec Référentiel Maroclear

## Nouveautés V5
- Intégration du fichier REP MCL Maroclear.
- Recherche par ISIN, mnémonique, émetteur, catégorie et type de taux.
- Mapping automatique Maroclear → type d'obligation dans l'application.
- Ajout direct d'un titre Maroclear au portefeuille.
- Import d'un portefeuille simple par ISIN puis enrichissement via Maroclear.
- Contrôles qualité du référentiel.
- Courbe BAM automatique + cache + historique.
- Spreads décomposés : crédit, liquidité, subordination, spécifique, ajustement marché.
- Échéancier personnalisé.
- Taux variables par table période par période.
- Dashboard portefeuille, buckets de maturité, contributions duration / PVBP.
- Stress tests : parallèle, steepening, flattening.
- Exports Excel et PDF.

## Lancement

Depuis le dossier qui contient app.py :

```cmd
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Avec Python 3.13 :

```cmd
C:\Users\pc\AppData\Local\Programs\Python\Python313\python.exe -m pip install -r requirements.txt
C:\Users\pc\AppData\Local\Programs\Python\Python313\python.exe -m streamlit run app.py
```

## Workflow recommandé
1. Onglet Courbe BAM : récupérer la courbe ou uploader une courbe.
2. Onglet Référentiel Maroclear : uploader le fichier REP MCL.
3. Onglet Recherche & ajout titre : chercher ISIN / mnémonique / émetteur.
4. Ajouter le titre au portefeuille.
5. Compléter quantité, spread et prix marché.
6. Analyser valorisation, risques, stress tests et exports.

## Fichiers modèles inclus
- modele_portefeuille_simple_isin.csv
- modele_echeancier_personnalise.csv
- modele_taux_variables.csv
- sample_courbe_bam.csv


## Correction V5.1
- Correction de l'erreur `AttributeError: 'float' object has no attribute 'pie'`.
- Protection contre l'ajout accidentel de titres déjà échus depuis Maroclear.
- Intérêts courus mis à zéro pour les titres déjà échus à la date de règlement.


## Optimisation V5.2
- Création d'une colonne `search_blob` pré-calculée dans le référentiel Maroclear.
- Recherche vectorisée avec `str.contains(..., regex=False)` au lieu de `apply()` ligne par ligne.
- Cache Streamlit de la lecture du fichier REP MCL.
- Suppression du gros menu déroulant des émetteurs, remplacé par un filtre texte rapide.
- Filtre `Non échus seulement` pour éviter les titres arrivés à maturité.
- Limitation paramétrable du nombre de résultats affichés.

## Nouveautés V6
- Gestion intelligente des nominaux Maroclear : PARVALUE, NEWPARVALUE, ISSUESIZE, ISSUECAPITAL.
- Séparation entre nominal Maroclear et nominal utilisé dans la valorisation.
- Choix du nominal lors de l'ajout Maroclear : Auto, PARVALUE, NEWPARVALUE, 100 000 MAD, ou manuel.
- Alertes pour nominal atypique sans bloquer la valorisation.
- Traitement spécial FPCT, obligations convertibles, amortissables et titres échus.
- Ajout du nominal total détenu = nominal utilisé × quantité.
- Nouvel onglet Calcul & formules avec les formules de valorisation par type d'obligation.
- Export Excel enrichi avec une feuille Formules.


## Correction V6.1
- Correction critique de la génération des coupons futurs.
- Le premier coupon futur utilise maintenant la date de coupon précédente réelle, pas la date d'émission.
- Ajout de contrôles `max_yf_coupon`, `first_coupon_yf`, `first_coupon_brut`.
- Correction du calcul `market_dirty_value` : le prix marché n'est utilisé que si le prix clean marché est strictement positif.
- Ajout d'alertes si le clean price dépasse 130% du nominal sur des obligations classiques.
- Rubrique Calcul & formules enrichie avec les formules réglementaires de référence AMMC/CDVM.


## Nouveautés V7
- Valorisation taux variable plus fiable sans import d'échéancier Excel.
- Ajout des dates avancées : date de jouissance, premier coupon, coupon précédent saisi, prochain coupon saisi.
- Gestion des cas : règlement avant jouissance, premier coupon court/long, coupon courant connu, titre échu.
- Ajout des dates de fixing : dernier fixing, prochain fixing.
- Ajout des modes de projection taux variable :
  1. Coupon courant fixé puis projection courbe
  2. Coupon courant constant jusqu'échéance
  3. Taux Maroclear/coupon facial constant
  4. Taux référence manuel constant + marge
  5. Courbe BAM + marge
- Le coupon Maroclear est utilisé comme coupon courant fixé par défaut pour les titres à taux variable importés depuis Maroclear.
- Formules enrichies dans la rubrique Calcul & formules.


## Nouveautés V8
- Nouveau mode recommandé pour les obligations à taux variable : `FRN par au prochain reset recommandé`.
- Ce mode valorise le coupon courant jusqu’au prochain reset et suppose un retour proche du pair au reset.
- Le prix clean d’une FRN devient naturellement proche de 100% si la marge contractuelle est cohérente avec le spread exigé.
- Conservation des autres modes : projection courbe, coupon courant constant, taux Maroclear constant, taux manuel + marge.
- Ajout d’alertes si une FRN sort trop loin du pair (<90% ou >110%).
- Formules enrichies dans l’onglet Calcul & formules.


## Nouveautés V9
- Nom d'application simplifié : Valorisation Obligataire Maroc.
- Suppression des messages explicatifs de version dans l'interface.
- Ajout d'une rubrique d'échéancier directement dans l'application.
- Construction d'un échéancier sans Excel : in fine, amortissement constant, zéro coupon ou manuel.
- Tableau éditable Streamlit : date_flux, coupon, principal, type_flux.
- Activation/suppression d'un échéancier personnalisé par obligation.
- Alerte FPCT reformulée avec une action claire : confirmer la structure dans la rubrique Saisie & échéancier.


## Correctifs V9.1
- Sélection Maroclear rendue plus robuste.
- Amortissement constant corrigé : basé sur le nombre total de périodes contractuelles, pas seulement les flux futurs.
- Capital restant dû ajusté pour les obligations amortissables déjà en vie.
- Intérêts courus FRN corrigés avec la table de taux variable lorsqu’elle est fournie.
- ACT/ACT traité en approche ICMA pour les périodes coupon.
- Remplacement de `pd.io.common.StringIO` par `io.StringIO`.
- Conversion des taux BAM plus robuste avec analyse de colonne.
- Alerte forte si la courbe utilisée est l’échantillon local et non une courbe BAM confirmée.
- Stress-tests ajustés pour les titres callable, puttable et convertibles de manière simplifiée.
- Ajout du mode d’actualisation dans le formulaire.


## Nouveautés V10
- Ergonomie simplifiée de l’échéancier.
- L’échéancier n’est plus saisi dans un bloc séparé encombrant.
- Les paramètres de taux variable se modifient directement après sélection du titre dans l’onglet Valorisation détaillée.
- Chaque titre dispose de sa propre table de taux variables et de son propre échéancier.
- Pré-remplissage automatique depuis les flux calculés ou les paramètres du titre.
- Édition contextuelle des FPCT, amortissables, structurés et FRN.
- Audit des intérêts courus ajouté dans la fiche de valorisation détaillée.


## V10.1
- Rubrique Calcul & formules réécrite dans un style plus naturel et plus orienté utilisateur.
- Suppression des formulations de version dans le bouton d’export.
- Le bouton Excel devient : Télécharger l’export Excel complet.
- Le rapport PDF est plus détaillé :
  - paramètres de valorisation ;
  - méthodologie ;
  - KPIs ;
  - résumé des titres ;
  - contributions au risque ;
  - scénarios ;
  - courbe utilisée ;
  - extrait des cash-flows ;
  - alertes, erreurs et points de contrôle.


## V10.2
- Correction de la gestion des courbes BAM uploadées.
- La courbe uploadée est maintenant stockée en session et prioritaire si activée.
- Ajout d'un statut clair : courbe uploadée active, courbe BAM automatique ou échantillon local.
- Ajout d'un modèle CSV de courbe BAM téléchargeable.
- Si le fichier uploadé n'est pas reconnu, l'application affiche les colonnes détectées.
- L'application ne revient plus silencieusement à l'échantillon local quand l'upload échoue.
- Export Excel/PDF bloqué si la courbe active est l'échantillon local.


## V10.3
- Lecture corrigée du CSV officiel BAM contenant deux lignes de titre avant l’en-tête.
- Détection automatique de la ligne d’en-tête `Date d'échéance;Transaction;Taux moyen pondéré;Date de la valeur`.
- Suppression automatique de la ligne `Total`.
- Support renforcé des taux au format `2,210 %`.


## V11
- Ajout d'une méthode réglementaire AMMC stricte pour les cas standards.
- Correction BDT court terme : numérateur = N*(1+tf*Mi/360).
- Correction obligations in fine avec maturité résiduelle <= 1 an : coupon annuel complet si Mi > 1 an.
- Correction lignes postérieures <= 1 an : coupon calculé sur Mi/A.
- Pour in fine > 1 an : prix AMMC avec taux unique interpolé à la maturité du titre.
- Ajout des colonnes de contrôle : prix_ammc, dirty_price_dcf, ecart_app_vs_dcf, formule_ammc, taux_ammc.
- Affichage de la méthode appliquée dans Valorisation détaillée.

## V11.1
- Correction de la formule AMMC (4) pour les obligations in fine de maturité résiduelle > 1 an.
- Utilise un taux unique, un premier décalage nj/A jusqu'au prochain coupon, puis des périodes annuelles entières.


## V12 — Conformité AMMC renforcée
- Ajout du champ `nature_ligne` : ligne normale / ligne postérieure.
- Ajout du champ `structure_flux_confirmee`.
- Ajout des formules AMMC pour lignes postérieures :
  - formule 4.2 : ligne postérieure avec un seul flux ;
  - formule 4.3 : ligne postérieure avant premier coupon avec plusieurs flux.
- Ajout d’un statut de conformité par titre :
  - Conforme AMMC ;
  - Conforme avec hypothèses contractuelles ;
  - Conforme avec échéancier utilisateur ;
  - Indicatif / hors périmètre.
- Scénarios de stress alignés avec la méthode de pricing active via `compute_metrics`.
- Stress crédit séparé via `credit_bps`.
- Ajout du mode FRN `Projection forwards + marge`.
- FPCT sans échéancier confirmé marqué comme indicatif / non conforme strict.


## V12.1
- Correction du coupon unitaire AMMC pour les obligations fixes in fine.
- Le coupon d'une obligation fixe in fine est désormais constant par période :
  `coupon = nominal × taux facial / fréquence`.
- Les années bissextiles ne gonflent plus le coupon annuel à 366/365.
- La formule AMMC 4.1 utilise directement le coupon unitaire constant.
- Test de référence MA0002008029 : dirty ≈ 113 234,2532 et clean % ≈ 111,2740%.


## V12.2
- Seuil court terme corrigé : l'application utilise maintenant une année calendaire avec `relativedelta(years=1)`, pas un simple seuil de 366 jours.
- Prix net fiscal AMMC corrigé : le net suit la même formule AMMC que le brut, avec fiscalité appliquée aux coupons/intérêts.
- Alerte opérationnelle si une ligne semble postérieure mais que le champ Nature de ligne reste à Ligne normale.
- Spread crédit par défaut mis à 0 bps pour les nouveaux titres et les ajouts Maroclear.
- Suppression de l'onglet Calcul & formules.
- Suppression de l'affichage comparatif DCF vs AMMC dans l'interface : l'app affiche les valeurs retenues.


## V12.3
- Correction ergonomique : dans l'ajout Maroclear, le champ `Spread crédit bps` vaut maintenant 0 par défaut.
- Correction ergonomique : dans la saisie manuelle, le fallback du spread crédit vaut maintenant 0 par défaut.
- Les titres nouvellement ajoutés ne prennent plus 40 bps automatiquement.


## V12.4
- Interpolation des taux arrondie à 3 chiffres après la virgule en pourcentage.
  Exemple : 3,221987% devient 3,222%.
- Le taux AMMC final après spread est également arrondi à 3 décimales en pourcentage.
- Les taux affichés dans l'interface utilisent 3 décimales.


## V13
- Détection automatique des lignes postérieures quand le premier coupon est supérieur à une période normale × 1,1.
- Ajout d'un fichier `tests.py` avec 5 cas AMMC de référence.
- Parallélisation de la valorisation ligne par ligne avec ThreadPoolExecutor.
- Cache Streamlit de la valorisation du portefeuille par hash JSON du portefeuille, dates, courbe et échéanciers.
- Détection dynamique de l'URL CSV BAM dans le HTML au lieu de dépendre uniquement du hash hardcodé.
- Stockage local SQLite des courbes BAM récupérées via `bam_db.py`.
- Fallback sur la dernière courbe SQLite si BAM est indisponible.
- Helpers de courbe de prime de risque par émetteur dans `maroclear_ref.py`.
- Ajout des métriques `zspread_market_bps` et `oas_bps`.
- Validation dates plus visible dans le formulaire.
- Rapport PDF enrichi avec traçabilité AMMC : formule, taux, Mi/Mr/nj, comparaison AMMC/DCF pour audit.
- Dossier `pages/` ajouté comme structure de migration multipage Streamlit.


## V13.1
- Correction du comptage des points de courbe BAM.
- Ajout du choix `Base de calcul des maturités` :
  - Date valeur BAM : conserve les points de la courbe tels que publiés par BAM.
  - Date de valeur souhaitée : mode strict/backtesting pouvant exclure les maturités très courtes.
- Suppression du `drop_duplicates` sur tenor_years seul.
- Ajout d'un diagnostic de sélection de courbe : lignes brutes, lignes après mode, points utilisés, lignes exclues.


## V13.3
- Correction fondamentale de l’interpolation AMMC : interpolation linéaire en jours de maturité, pas en fractions d’années.
  Formule : tr = t1 + (t2 - t1) × (M - M1) / (M2 - M1).
- Les appels AMMC utilisent maintenant target_days = maturité résiduelle exacte en jours.
- Les cash-flows DCF utilisent aussi target_days = date_flux - date_règlement pour l’interpolation.
- Correction ACT/ACT fallback : passage à ACT/ACT ISDA multi-années.
- Correction du reste de logique cash-flow : le test `<= 366 jours` est remplacé par `within_one_calendar_year(...)`.
- Ajout de tests unitaires pour interpolation en jours et ACT/ACT ISDA.


## V14
- Correction critique FRN : `taux_actu` est maintenant défini dans `build_frn_reset_proxy_cashflow`.
- Correction AMMC 4.1 pour coupons non annuels : exposants en `first_offset + (k-1)/fréquence`.
- Correction AMMC 4.3 ligne postérieure : coupon périodique = `N*tf/fréquence` et exposants corrigés.
- Sensibilités : calcul sur ±10 bps et désactivation de l’arrondi de taux dans `price_from_cf` pour éviter les effets d’arrondi.
- Amortissables : intérêts courus calculés sur le capital restant dû, avec support d’un `CRD manuel amortissable`.
- Amortissables sans échéancier contractuel : statut `Non conforme — échéancier contractuel requis`.
- Saisie : affichage immédiat des résultats dans le même onglet après ajout/modification du titre.
- Tests V14 ajoutés : FRN reset, in fine semestriel, IC amortissable sur CRD.


## V14.1
- Correction amortissables : le `CRD manuel amortissable` pilote désormais tout l'échéancier futur.
- Si CRD manuel > 0 :
  - capital_debut du premier flux = CRD manuel ;
  - amortissement futur = CRD manuel / nombre de flux futurs restants ;
  - coupons futurs calculés sur le CRD restant ;
  - somme des principaux futurs = CRD manuel ;
  - intérêts courus calculés sur le même CRD.
- Ajout de diagnostics : `capital_restant_du_manuel`, `crd_manuel_pilote_cashflows`, `crd_manuel_utilise`.
- Ajout d'un test unitaire dédié : `test_amortissable_crd_manuel_pilote_cashflows`.


## V14.2
- Correction coupon long : si `premier coupon - jouissance` dépasse une période normale × 1,10 et que le coupon long n'est pas autorisé, l'app insère des dates intermédiaires régulières.
- Ajout du champ `Autoriser coupon long contractuel` : à cocher uniquement si la note d'information confirme le coupon long.
- Ajout des diagnostics : `coupon_long_count`, `coupon_long_non_confirme_count`, `yf_coupon_normal`.
- Si un coupon long non confirmé reste détecté, la conformité passe à `Non conforme — coupon long non confirmé`.
- Ajout du mode amortissable `Annuités constantes`.
- Tests ajoutés : coupon long non autorisé, coupon long autorisé, annuités constantes.


## V15
- Recheck complet du fichier Maroclear `REP MCL 04-05-2026`.
- Correction centrale : le référentiel Maroclear ne supprime plus les lignes multiples par ISIN liées à `CouponPayDate`.
- Les dates `CouponPayDate` sont maintenant agrégées dans `maroclear_coupon_dates` et utilisées par le moteur de cash-flows.
- Le calendrier de coupon utilise `Maroclear CouponPayDate` et reconstruit automatiquement le coupon précédent par rétro-propagation pour les intérêts courus.
- Les champs Maroclear intégrés et traçables incluent :
  - INSTRID, INSTRTYPE, INSTRCTGRY, ISSUEDT, MATURITYDT_L, PARVALUE, NEWPARVALUE,
  - INTERESTTYPE, INTERESTPERIODCTY, INTERESTRATE,
  - REDEMPTIONTYPE, AMORTFREQ, CouponPayDate, PRMYDTLSDUMMYDATE1.
- Correction du mapping TCN : les TCN sont traités en court terme 360 jours.
- Correction des codes fréquence Maroclear : ANLY, HFLY, QTLY.
- Spread par défaut corrigé à 0 bps aussi dans l'import portefeuille simplifié.
- Ajout d'un mode de pricing `YTM fourni / gérant` pour la réconciliation sans ajustement artificiel de spread.
- Correction de la fausse détection ligne postérieure quand le calendrier Maroclear est disponible.
- Tests V15 ajoutés pour :
  - agrégation CouponPayDate Maroclear ;
  - mapping TCN ;
  - rétro-propagation du coupon précédent depuis les dates Maroclear.


## V15.1
- Correction amortissables : coupon constant par période sur CRD (`CRD × taux / fréquence`) au lieu de `CRD × taux × yf_coupon`.
- Correction audit : `taux_actualisation` affiché dans les cash-flows stocke désormais le taux arrondi réellement utilisé (`taux_actu`).
- Contrôle amortissables avec différé :
  - nouveau mode `Différé d’amortissement / CRD obligatoire` ;
  - si aucun CRD manuel n’est renseigné, la valorisation passe en non conforme.
- Vérification post-calcul :
  - `amortissement_crd_initial_calcule`
  - `amortissement_principal_sum`
  - `amortissement_principal_gap`
- Export simplifié ajouté :
  - Excel simplifié : ISIN, émetteur, type, dirty price, taux utilisé ;
  - PDF simplifié : dirty price et taux utilisé par titre.
- Le rapport détaillé garde les cash-flows, mais la section est renommée `cash-flows indicatifs` pour éviter la confusion avec le prix AMMC réglementaire.


## V15.2
- Contrôle spread explicite :
  1. interpolation du taux courbe ;
  2. arrondi du taux courbe à 3 décimales en pourcentage ;
  3. ajout du spread ;
  4. arrondi du taux total à 3 décimales en pourcentage.
- Exemple validé : 3,221987% -> 3,222% ; +80 bps -> 4,022%.
- `taux_actualisation` des cash-flows stocke le taux total réellement utilisé.
- `price_from_cf` utilise le taux affiché/arrondi comme base pour éviter une différence entre affichage et calcul.
- Tests ajoutés :
  - `test_spread_added_after_curve_rounding`
  - `test_cashflow_taux_actualisation_spread_after_rounding`


## V16

Elle conserve les corrections récentes :
- intégration Maroclear / CouponPayDate ;
- export simplifié Excel + PDF ;
- coupon amortissable régulier = CRD × taux / fréquence ;
- contrôle différé d’amortissement / CRD obligatoire ;
- vérification Σ amortissements futurs vs CRD ;
- spread ajouté après arrondi du taux courbe.
