from google.appengine.api import users
from google.appengine.api import images
from google.appengine.api import urlfetch
from google.appengine.api.labs import taskqueue
from google.appengine.ext import db
from google.appengine.runtime import DeadlineExceededError
from google.appengine.runtime.apiproxy_errors import CancelledError
import os
from os import environ
import urllib
import constants
import logging
from datetime import datetime
from gheatae import tile
from models import MapImage, UserInfo

def draw_static_tile(user, mapimage_key, zoom, northlat, westlng, offset_x_px, offset_y_px):
  new_tile = tile.CustomTile(user, zoom, northlat, westlng, offset_x_px, offset_y_px)
  def compose_and_save(key, tile, x, y): # this has to be done in a transaction - otherwise the different threads will overwrite each other's progress on the shared mapimage
    mapimage = db.get(key)
    input_tuples = [(tile.image_out(), x, y, 1.0, images.TOP_LEFT)]
    if mapimage.img:
      input_tuples.append((mapimage.img, 0, 0, 1.0, images.TOP_LEFT))
    img = images.composite(inputs=input_tuples, width=mapimage.width, height=mapimage.height, color=0, output_encoding=images.PNG) # redraw main image every time to show progress
    mapimage.img = db.Blob(img)
    mapimage.last_updated = datetime.now()
    mapimage.put()
  db.run_in_transaction(compose_and_save, mapimage_key, new_tile, offset_x_px, offset_y_px)

def generate_static_map(user, widthxheight, zoom, centerpoint, northwest):
  try:
    assert widthxheight.count('x') == 1, "%d x's" % centerpoint.count('x')
    width, height = widthxheight.split('x')
    assert zoom.isdigit(), "not digits"
    assert centerpoint.count(',') == 1, "%d ,'s" % centerpoint.count(',')
    centerlat, centerlng = centerpoint.split(',')
    assert northwest.count(',') == 1, "%d ,'s" % northwest.count(',')
    northlat, westlng = northwest.split(',')
  except AssertionError, err:
    logging.error(err.args[0])
    return
  try:
    google_data = {
      'key': constants.get_google_maps_apikey(),
      'zoom': zoom,
      'center': centerpoint,
      'size': widthxheight,
      'sensor':'false',
      'format':'png',
    }
    mapimage = MapImage.all().filter('user =', user).get()
    if not mapimage:
      mapimage              = MapImage()
      mapimage.user         = user
      mapimage.update_count = 0
    mapimage.centerlat  = float(centerlat)
    mapimage.centerlng  = float(centerlng)
    mapimage.northlat   = float(northlat)
    mapimage.westlng    = float(westlng)
    mapimage.zoom       = int(zoom)
    mapimage.height     = int(height)
    mapimage.width      = int(width)
    mapimage.static_url = "http://maps.google.com/maps/api/staticmap?" + urllib.urlencode(google_data)
    mapimage.put()
    for offset_x_px in range (0, mapimage.width, 256):
      for offset_y_px in range (0, mapimage.height, 256):
        taskqueue.add(queue_name='tiles', url='/draw_static_tile/%s/%d/%f/%f/%d/%d' % (mapimage.key(), mapimage.zoom, mapimage.northlat, mapimage.westlng, offset_x_px, offset_y_px))
  except DeadlineExceededError, err:    
    logging.error("Ran out of time before creating a map! %s" % err)

if __name__ == '__main__':
  fragments = environ['PATH_INFO'].split('/')
  fragments.pop(0)
  func = fragments.pop(0)
  user = users.get_current_user()
  try:
    if user and func == 'generate_static_map':
      assert len(fragments) == 4, "fragments should have 4 elements %s" % str(fragments)
      widthxheight, zoom, centerpoint, northwest = fragments
      generate_static_map(user, widthxheight, zoom, centerpoint, northwest)
    elif func == 'draw_static_tile':
      mapimage_key = fragments.pop(0)
      mapimage = db.get(mapimage_key)
      if mapimage:
        assert len(fragments) == 5, "fragments should have 5 elements %s" % str(fragments)
        zoom, northlat, westlng, offset_x_px, offset_y_px = fragments
        draw_static_tile(mapimage.user, mapimage_key, int(zoom), float(northlat), float(westlng), int(offset_x_px), int(offset_y_px))
      else: 
        logging.warning('No mapimage found for key %s' % mapimage_key)
  except AssertionError, err:
    logging.error(err.args[0])
