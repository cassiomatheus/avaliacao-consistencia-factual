from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from factual_eval.fase1_referencia.extraction import main
if __name__=='__main__':main()
