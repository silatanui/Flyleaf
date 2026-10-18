# Bundled T5 tokenizer

Small SentencePiece files for the Lynote humanizer. They are committed so
cPanel can load the tokenizer even when `models/humanizer/en/spiece.model`
was missing from an SFTP upload. Weights (`model.safetensors`) still live
under `models/` and are not in git.
