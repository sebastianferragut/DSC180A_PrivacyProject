#!/bin/bash
# Setup script for Screenshot Summarization Environment

echo "🚀 Setting up Screenshot Summarization Environment..."

# Activate conda environment
conda activate screenshot-summarizer

# Set API key
export GEMINI_API_KEY="AIzaSyAB1Vmbb-Lo7RTSq0pipDFkBf8Q7pMG7QU"

echo "✅ Environment activated and API key set!"
echo "📝 You can now run your screenshot summarization scripts"
echo ""
echo "💡 To use this setup in the future, run:"
echo "   source setup_env.sh"
