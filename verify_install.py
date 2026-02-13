import sys
try:
    import torch
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"CUDA device: {torch.cuda.get_device_name(0)}")
except ImportError as e:
    print(f"Error importing torch: {e}")

try:
    import uvicorn
    print(f"Uvicorn version: {uvicorn.__version__}")
except ImportError as e:
    print(f"Error importing uvicorn: {e}")

print("Verification script finished.")
