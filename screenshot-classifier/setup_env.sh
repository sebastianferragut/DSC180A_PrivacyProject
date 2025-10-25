#!/bin/bash
# Setup script for Screenshot Summarization Environment
#
# To set up your API key, run this command first:
#   export GEMINI_API_KEY="your_api_key_here"
#
# Or add it to your ~/.bashrc or ~/.zshrc to make it permanent:
#   echo 'export GEMINI_API_KEY="your_api_key_here"' >> ~/.bashrc
#

echo "🚀 Setting up Screenshot Summarization Environment..."

# Activate conda environment
conda activate screenshot-summarizer

# Check if API key is set
if [ -z "$GEMINI_API_KEY" ]; then
    echo "⚠️  WARNING: GEMINI_API_KEY is not set!"
    echo ""
    echo "📝 Please set your API key by running:"
    echo "   export GEMINI_API_KEY=\"your_api_key_here\""
    echo ""
    echo "💡 Or add it permanently to your shell config:"
    echo "   echo 'export GEMINI_API_KEY=\"your_api_key_here\"' >> ~/.zshrc"
    echo ""
else
    echo "✅ Environment activated and API key is set!"
fi

echo "📝 You can now run your screenshot summarization scripts"
echo ""
echo "💡 To use this setup in the future, run:"
echo "   source setup_env.sh"
