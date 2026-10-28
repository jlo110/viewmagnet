"""
Efficient CNN feature extraction in batches.
Processes thumbnails incrementally and saves to cache.
"""

import numpy as np
import requests
from io import BytesIO
from PIL import Image
import pickle
from pathlib import Path
from tqdm import tqdm
import gc
import time

import torch
import torchvision.models as models
import torchvision.transforms as transforms

from src.database.models import Video, VideoFeatures, Channel
from src.database.connection import get_session
from sqlalchemy import and_


def extract_cnn_embeddings(batch_size: int = 100, max_samples: int = None):
    """Extract CNN embeddings in batches, saving progress."""
    
    cache_file = Path("data/cnn_embeddings_cache.pkl")
    cache_file.parent.mkdir(exist_ok=True)
    
    # Load existing cache
    if cache_file.exists():
        with open(cache_file, 'rb') as f:
            cache = pickle.load(f)
        print(f"📂 Loaded {len(cache):,} cached embeddings")
    else:
        cache = {}
    
    # Get all thumbnail URLs from database
    print("📊 Loading video URLs from database...")
    with get_session() as session:
        query = session.query(Video.thumbnail_url).join(
            VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).join(
            Channel, Video.channel_id == Channel.channel_id
        ).filter(and_(
            Video.view_count >= 100,
            VideoFeatures.thumbnail_processed == True,
            Channel.avg_views_per_video > 0,
            Channel.niche_id.isnot(None)
        ))
        
        if max_samples:
            query = query.limit(max_samples)
        
        all_urls = [r[0] for r in query.all()]
    
    print(f"   Total videos: {len(all_urls):,}")
    
    # Filter out already cached
    urls_needed = [url for url in all_urls if url not in cache]
    print(f"   Already cached: {len(all_urls) - len(urls_needed):,}")
    print(f"   Need to process: {len(urls_needed):,}")
    
    if not urls_needed:
        print("✅ All embeddings already cached!")
        return cache
    
    # Load model
    print("\n🧠 Loading MobileNetV3 (lightweight)...")
    model = models.mobilenet_v3_small(weights='IMAGENET1K_V1')
    model.eval()
    
    # Remove classifier to get embeddings (576-dim for MobileNetV3-Small)
    model.classifier = torch.nn.Identity()
    
    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], 
                           std=[0.229, 0.224, 0.225])
    ])
    
    device = torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
    model = model.to(device)
    print(f"   Using device: {device}")
    
    # Process in batches
    print(f"\n🔄 Processing {len(urls_needed):,} thumbnails in batches of {batch_size}...")
    
    success = 0
    failed = 0
    
    for i in tqdm(range(0, len(urls_needed), batch_size), desc="Batches"):
        batch_urls = urls_needed[i:i+batch_size]
        batch_images = []
        valid_urls = []
        
        # Download batch
        for url in batch_urls:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    img = Image.open(BytesIO(response.content)).convert('RGB')
                    batch_images.append(transform(img))
                    valid_urls.append(url)
            except:
                failed += 1
        
        if batch_images:
            # Process batch
            batch_tensor = torch.stack(batch_images).to(device)
            
            with torch.no_grad():
                embeddings = model(batch_tensor).cpu().numpy()
            
            # Save to cache
            for url, emb in zip(valid_urls, embeddings):
                cache[url] = emb
                success += 1
            
            # Clean up memory
            del batch_tensor, embeddings, batch_images
            torch.mps.empty_cache() if device.type == 'mps' else None
            gc.collect()
        
        # Save cache periodically (every 10 batches)
        if (i // batch_size) % 10 == 0 and i > 0:
            with open(cache_file, 'wb') as f:
                pickle.dump(cache, f)
            tqdm.write(f"   💾 Saved {len(cache):,} embeddings to cache")
    
    # Final save
    with open(cache_file, 'wb') as f:
        pickle.dump(cache, f)
    
    print(f"\n✅ Complete!")
    print(f"   Success: {success:,}")
    print(f"   Failed: {failed:,}")
    print(f"   Total cached: {len(cache):,}")
    
    return cache


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-size', type=int, default=50, help='Batch size')
    parser.add_argument('--max-samples', type=int, default=None, help='Max samples to process')
    args = parser.parse_args()
    
    extract_cnn_embeddings(
        batch_size=args.batch_size,
        max_samples=args.max_samples
    )

