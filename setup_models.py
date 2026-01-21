#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para descargar e inicializar los modelos de NLP.

Ejecutar una vez antes de usar el sistema con embeddings:
    python setup_models.py
"""
import sys
import os

def setup_models():
    """Descarga e inicializa los modelos necesarios."""
    
    print("="*60)
    print("Configurando modelos de NLP para Domain Finder")
    print("="*60)
    
    # 1. Instalar dependencias si no están
    print("\n[1/3] Verificando dependencias...")
    try:
        import sentence_transformers
        print("  ✓ sentence-transformers instalado")
    except ImportError:
        print("  → Instalando sentence-transformers...")
        os.system("pip install sentence-transformers")
    
    try:
        import fasttext
        print("  ✓ fasttext instalado")
    except ImportError:
        print("  → Instalando fasttext-wheel...")
        os.system("pip install fasttext-wheel")
    
    try:
        import numpy
        print("  ✓ numpy instalado")
    except ImportError:
        print("  → Instalando numpy...")
        os.system("pip install numpy")
    
    try:
        import sklearn
        print("  ✓ scikit-learn instalado")
    except ImportError:
        print("  → Instalando scikit-learn...")
        os.system("pip install scikit-learn")
    
    # 2. Descargar modelo de Sentence-Transformers
    print("\n[2/3] Descargando modelo Sentence-Transformers...")
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        # Test rápido
        test_embedding = model.encode("test")
        print(f"  ✓ Modelo cargado (dimensión: {len(test_embedding)})")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False
    
    # 3. Descargar modelo FastText (opcional pero recomendado)
    print("\n[3/3] Configurando FastText...")
    try:
        import fasttext
        import fasttext.util
        from pathlib import Path
        
        model_path = Path.home() / ".cache" / "fasttext" / "cc.es.50.bin"
        
        if model_path.exists():
            print(f"  ✓ Modelo ya existe en {model_path}")
        else:
            print("  → Descargando modelo español (puede tardar varios minutos)...")
            model_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Descargar modelo completo
            fasttext.util.download_model('es', if_exists='ignore')
            
            # Reducir dimensiones para eficiencia
            print("  → Reduciendo dimensiones del modelo...")
            ft = fasttext.load_model('cc.es.300.bin')
            fasttext.util.reduce_model(ft, 50)
            ft.save_model(str(model_path))
            
            # Limpiar modelo grande
            if os.path.exists('cc.es.300.bin'):
                os.remove('cc.es.300.bin')
            
            print(f"  ✓ Modelo guardado en {model_path}")
        
        # Test rápido
        ft = fasttext.load_model(str(model_path))
        test_vec = ft.get_sentence_vector("test")
        print(f"  ✓ FastText funcionando (dimensión: {len(test_vec)})")
        
    except Exception as e:
        print(f"  ⚠ FastText no disponible: {e}")
        print("    El sistema funcionará sin tolerancia avanzada a errores")
    
    print("\n" + "="*60)
    print("✓ Configuración completada")
    print("="*60)
    print("\nAhora puedes ejecutar: streamlit run app.py")
    
    return True


if __name__ == "__main__":
    success = setup_models()
    sys.exit(0 if success else 1)
