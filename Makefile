.PHONY: nanochat-setup nanochat-train clean



# run nothing by default.
all: 



nanochat-setup:
	cd nanochat && pip install -r requirements.txt

nanochat-train:
	cd nanochat && python train.py --config config/default.yaml

clean:
	cd nanochat && rm -rf __pycache__ *.pyc
