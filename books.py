"""Codes livres (USFM, comme dans les URL lire.la-bible.net) et testaments."""
OT = ["GEN","EXO","LEV","NUM","DEU","JOS","JDG","RUT","1SA","2SA","1KI","2KI","1CH","2CH",
      "EZR","NEH","EST","JOB","PSA","PRO","ECC","SNG","ISA","JER","LAM","EZK","DAN","HOS",
      "JOL","AMO","OBA","JON","MIC","NAM","HAB","ZEP","HAG","ZEC","MAL"]
NT = ["MAT","MRK","LUK","JHN","ACT","ROM","1CO","2CO","GAL","EPH","PHP","COL","1TH","2TH",
      "1TI","2TI","TIT","PHM","HEB","JAS","1PE","2PE","1JN","2JN","3JN","JUD","REV"]
BOOKS = OT + NT

NAMES = {
 "GEN":"Genèse","EXO":"Exode","LEV":"Lévitique","NUM":"Nombres","DEU":"Deutéronome","JOS":"Josué",
 "JDG":"Juges","RUT":"Ruth","1SA":"1 Samuel","2SA":"2 Samuel","1KI":"1 Rois","2KI":"2 Rois",
 "1CH":"1 Chroniques","2CH":"2 Chroniques","EZR":"Esdras","NEH":"Néhémie","EST":"Esther","JOB":"Job",
 "PSA":"Psaumes","PRO":"Proverbes","ECC":"Ecclésiaste","SNG":"Cantique des cantiques","ISA":"Ésaïe",
 "JER":"Jérémie","LAM":"Lamentations","EZK":"Ézéchiel","DAN":"Daniel","HOS":"Osée","JOL":"Joël",
 "AMO":"Amos","OBA":"Abdias","JON":"Jonas","MIC":"Michée","NAM":"Nahum","HAB":"Habacuc",
 "ZEP":"Sophonie","HAG":"Aggée","ZEC":"Zacharie","MAL":"Malachie","MAT":"Matthieu","MRK":"Marc",
 "LUK":"Luc","JHN":"Jean","ACT":"Actes","ROM":"Romains","1CO":"1 Corinthiens","2CO":"2 Corinthiens",
 "GAL":"Galates","EPH":"Éphésiens","PHP":"Philippiens","COL":"Colossiens","1TH":"1 Thessaloniciens",
 "2TH":"2 Thessaloniciens","1TI":"1 Timothée","2TI":"2 Timothée","TIT":"Tite","PHM":"Philémon",
 "HEB":"Hébreux","JAS":"Jacques","1PE":"1 Pierre","2PE":"2 Pierre","1JN":"1 Jean","2JN":"2 Jean",
 "3JN":"3 Jean","JUD":"Jude","REV":"Apocalypse",
}

def scope_codes(scope):
    if isinstance(scope, list):
        return [c for c in BOOKS if c in scope]
    return {"NT": NT, "OT": OT, "ALL": BOOKS}[scope]
