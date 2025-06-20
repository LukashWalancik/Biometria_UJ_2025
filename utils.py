import math
import numpy as np
import cv2 as cv
import urllib.request
import IPython
import base64
import html

def do_the_thing(fingerprint_path: str) -> None:
    fingerprint = cv.imread(fingerprint_path, cv.IMREAD_GRAYSCALE)
    gx, gy = cv.Sobel(fingerprint, cv.CV_32F, 1, 0), cv.Sobel(fingerprint, cv.CV_32F, 0, 1)
    gx2, gy2 = gx**2, gy**2
    gm = np.sqrt(gx2 + gy2)

    sum_gm = cv.boxFilter(gm, -1, (25, 25), normalize = False)
    thr = sum_gm.max() * 0.2
    mask = cv.threshold(sum_gm, thr, 255, cv.THRESH_BINARY)[1].astype(np.uint8)

    W = (23, 23)
    gxx = cv.boxFilter(gx2, -1, W, normalize = False)
    gyy = cv.boxFilter(gy2, -1, W, normalize = False)
    gxy = cv.boxFilter(gx * gy, -1, W, normalize = False)
    gxx_gyy = gxx - gyy
    gxy2 = 2 * gxy

    orientations = (cv.phase(gxx_gyy, -gxy2) + np.pi) / 2 # '-' to adjust for y axis direction
    sum_gxx_gyy = gxx + gyy
    strengths = np.divide(cv.sqrt((gxx_gyy**2 + gxy2**2)), sum_gxx_gyy, out=np.zeros_like(gxx), where=sum_gxx_gyy!=0)

    singular_points = calculate_poincare_index(orientations, mask, step=10, window_size=6)
    singular_points = merge_nearby_points(singular_points, distance_threshold=50)

    result_image = draw_orientations(fingerprint, orientations, strengths, mask, 1, 16)
    for sp in singular_points:
        x, y = sp['coords']
        scaled_x, scaled_y = x, y
        color = (0, 255, 255) if sp['type'] == 'core' else (0, 255, 0)
        cv.circle(result_image, (scaled_x, scaled_y), 30, color, 2)
        cv.putText(result_image, sp['type'], (scaled_x + 50, scaled_y), cv.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    show(fingerprint, mask, result_image)

    fingerprint_class = classify_fingerprint(singular_points)
    print(f"\nKlasa odcisku palca: {fingerprint_class}")

def merge_nearby_points(singular_points, distance_threshold=80):
    if not singular_points:
        return []

    merged_points = []
    for sp1 in singular_points:
        is_merged = False
        for sp2 in merged_points:
            dist = np.sqrt((sp1['coords'][0] - sp2['coords'][0])**2 + (sp1['coords'][1] - sp2['coords'][1])**2)
            if dist < distance_threshold:
                is_merged = True
                break
        if not is_merged:
            merged_points.append(sp1)
    return merged_points

def classify_fingerprint(singular_points):
    cores = [sp for sp in singular_points if sp['type'] == 'core']
    deltas = [sp for sp in singular_points if sp['type'] == 'delta']
    whorl_cores = [sp for sp in singular_points if sp['type'] == 'whorl_core']

    num_cores = len(cores) + len(whorl_cores)
    num_deltas = len(deltas)

    if num_cores >= 2 and num_deltas >= 2:
        return "Wir (Whorl)"
    elif num_cores == 1 and num_deltas == 1:
        core_x, core_y = cores[0]['coords']
        delta_x, delta_y = deltas[0]['coords']
        if core_x > delta_x:
            return "Pętla Prawa (Right Loop)"
        else:
            return "Pętla Lewa (Left Loop)"
    elif num_cores == 1 and num_deltas == 0:
        return "Namiotowy Łuk (Tented Arch) / Pętla (niekompletna)"
    elif num_cores == 0 and num_deltas == 0:
        return "Łuk (Arch)"
    else:
        return "Niesklasyfikowany / Nietypowy"

def calculate_poincare_index(orientations, mask, step=16, window_size=3, poincare_tolerance_degrees=45):
    h, w = orientations.shape
    singular_points = []
    
    for y in range(window_size, h - window_size, step):
        for x in range(window_size, w - window_size, step):
            if mask[y, x] == 0:
                continue
            path_points = []
            for i in range(x - window_size, x + window_size + 1):
                path_points.append((i, y - window_size))
            for j in range(y - window_size + 1, y + window_size + 1):
                path_points.append((x + window_size, j))
            for i in range(x + window_size - 1, x - window_size - 1, -1):
                path_points.append((i, y + window_size))
            for j in range(y + window_size - 1, y - window_size, -1):
                path_points.append((x - window_size, j))

            unique_path_points = []
            seen = set()
            for px, py in path_points:
                if mask[py, px] == 0:
                    break
                if 0 <= px < w and 0 <= py < h and mask[py, px] != 0:
                    if (px, py) not in seen:
                        unique_path_points.append((px, py))
                        seen.add((px, py))
            
            path_points = unique_path_points
            
            if len(path_points) < 8:
                continue

            poincare_index_radians = 0
            N = len(path_points)
            for i in range(N):
                p1_x, p1_y = path_points[i]
                p2_x, p2_y = path_points[(i + 1) % N]
                
                theta1 = orientations[p1_y, p1_x]
                theta2 = orientations[p2_y, p2_x]
                
                diff = theta2 - theta1
                if diff > np.pi / 2:
                    diff -= np.pi
                elif diff < -np.pi / 2:
                    diff += np.pi
                
                poincare_index_radians += diff
            
            poincare_index_degrees = np.degrees(poincare_index_radians)
            
            if abs(poincare_index_degrees + 180) < poincare_tolerance_degrees:
                singular_points.append({'type': 'core', 'coords': (x, y), 'index': poincare_index_degrees})
            elif abs(poincare_index_degrees - 180) < poincare_tolerance_degrees:
                singular_points.append({'type': 'delta', 'coords': (x, y), 'index': poincare_index_degrees})
            elif abs(poincare_index_degrees - 360) < poincare_tolerance_degrees:
                singular_points.append({'type': 'whorl_core', 'coords': (x, y), 'index': poincare_index_degrees})

    return singular_points

# Utility function to show an image
def show(*images, enlarge_small_images = True, max_per_row = -1, font_size = 0):
  if len(images) == 2 and type(images[1])==str:
      images = [(images[0], images[1])]

  def convert_for_display(img):
      if img.dtype!=np.uint8:
          a, b = img.min(), img.max()
          if a==b:
              offset, mult, d = 0, 0, 1
          elif a<0:
              offset, mult, d = 128, 127, max(abs(a), abs(b))
          else:
              offset, mult, d = 0, 255, b
          img = np.clip(offset + mult*(img.astype(float))/d, 0, 255).astype(np.uint8)
      return img

  def convert(imgOrTuple):
      try:
          img, title = imgOrTuple
          if type(title)!=str:
              img, title = imgOrTuple, ''
      except ValueError:
          img, title = imgOrTuple, ''        
      if type(img)==str:
          data = img
      else:
          img = convert_for_display(img)
          if enlarge_small_images:
              REF_SCALE = 100
              h, w = img.shape[:2]
              if h<REF_SCALE or w<REF_SCALE:
                  scale = max(1, min(REF_SCALE//h, REF_SCALE//w))
                  img = cv.resize(img,(w*scale,h*scale), interpolation=cv.INTER_NEAREST)
          data = 'data:image/png;base64,' + base64.b64encode(cv.imencode('.png', img)[1]).decode('utf8')
      return data, title
    
  if max_per_row == -1:
      max_per_row = len(images)

  rows = [images[x:x+max_per_row] for x in range(0, len(images), max_per_row)]
  font = f"font-size: {font_size}px;" if font_size else ""

  html_content = ""
  for r in rows:
      l = [convert(t) for t in r]
      html_content += "".join(["<table><tr>"] 
              + [f"<td style='text-align:center;{font}'>{html.escape(t)}</td>" for _,t in l]    
              + ["</tr><tr>"] 
              + [f"<td style='text-align:center;'><img src='{d}'></td>" for d,_ in l]
              + ["</tr></table>"])
  IPython.display.display(IPython.display.HTML(html_content))

# Utility function to load an image from an URL
def load_from_url(url):
  resp = urllib.request.urlopen(url)
  image = np.asarray(bytearray(resp.read()), dtype=np.uint8)
  return cv.imdecode(image, cv.IMREAD_GRAYSCALE)

# Utility function to draw orientations over an image
def draw_orientations(fingerprint, orientations, strengths, mask, scale = 3, step = 8, border = 0):
    if strengths is None:
        strengths = np.ones_like(orientations)
    h, w = fingerprint.shape
    sf = cv.resize(fingerprint, (w*scale, h*scale), interpolation = cv.INTER_NEAREST)
    res = cv.cvtColor(sf, cv.COLOR_GRAY2BGR)
    d = (scale // 2) + 1
    sd = (step+1)//2
    c = np.round(np.cos(orientations) * strengths * d * sd).astype(int)
    s = np.round(-np.sin(orientations) * strengths * d * sd).astype(int) # minus for the direction of the y axis
    thickness = 1 + scale // 5
    for y in range(border, h-border, step):
        for x in range(border, w-border, step):
            if mask is None or mask[y, x] != 0:
                ox, oy = c[y, x], s[y, x]
                cv.line(res, (d+x*scale-ox,d+y*scale-oy), (d+x*scale+ox,d+y*scale+oy), (255,0,0), thickness, cv.LINE_AA)
    return res

# Utility function to draw a set of minutiae over an image
def draw_minutiae(fingerprint, minutiae, termination_color = (255,0,0), bifurcation_color = (0,0,255)):
    res = cv.cvtColor(fingerprint, cv.COLOR_GRAY2BGR)
    
    for x, y, t, *d in minutiae:
        color = termination_color if t else bifurcation_color
        if len(d)==0:
            cv.drawMarker(res, (x,y), color, cv.MARKER_CROSS, 8)
        else:
            d = d[0]
            ox = int(round(math.cos(d) * 7))
            oy = int(round(math.sin(d) * 7))
            cv.circle(res, (x,y), 3, color, 1, cv.LINE_AA)
            cv.line(res, (x,y), (x+ox,y-oy), color, 1, cv.LINE_AA)        
    return res

# Utility function to generate gabor filter kernels

_sigma_conv = (3.0/2.0)/((6*math.log(10))**0.5)
# sigma is adjusted according to the ridge period, so that the filter does not contain more than three effective peaks 
def _gabor_sigma(ridge_period):
    return _sigma_conv * ridge_period

def _gabor_size(ridge_period):
    p = int(round(ridge_period * 2 + 1))
    if p % 2 == 0:
        p += 1
    return (p, p)

def gabor_kernel(period, orientation):
    f = cv.getGaborKernel(_gabor_size(period), _gabor_sigma(period), np.pi/2 - orientation, period, gamma = 1, psi = 0)
    f /= f.sum()
    f -= f.mean()
    return f


# Utility functions for minutiae
def angle_abs_difference(a, b):
    return math.pi - abs(abs(a - b) - math.pi)

def angle_mean(a, b):
    return math.atan2((math.sin(a)+math.sin(b))/2, ((math.cos(a)+math.cos(b))/2))

# Utility functions for MCC
def draw_minutiae_and_cylinder(fingerprint, origin_cell_coords, minutiae, values, i, show_cylinder = True):

    def _compute_actual_cylinder_coordinates(x, y, t, d):
        c, s = math.cos(d), math.sin(d)
        rot = np.array([[c, s],[-s, c]])    
        return (rot@origin_cell_coords.T + np.array([x,y])[:,np.newaxis]).T
    
    res = draw_minutiae(fingerprint, minutiae)    
    if show_cylinder:
        for v, (cx, cy) in zip(values[i], _compute_actual_cylinder_coordinates(*minutiae[i])):
            cv.circle(res, (int(round(cx)), int(round(cy))), 3, (0,int(round(v*255)),0), 1, cv.LINE_AA)
    return res

def draw_match_pairs(f1, m1, v1, f2, m2, v2, cells_coords, pairs, i, show_cylinders = True):
    #nd = _current_parameters.ND
    h1, w1 = f1.shape
    h2, w2 = f2.shape
    p1, p2 = pairs
    res = np.full((max(h1,h2), w1+w2, 3), 255, np.uint8)
    res[:h1,:w1] = draw_minutiae_and_cylinder(f1, cells_coords, m1, v1, p1[i], show_cylinders)
    res[:h2,w1:w1+w2] = draw_minutiae_and_cylinder(f2, cells_coords, m2, v2, p2[i], show_cylinders)
    for k, (i1, i2) in enumerate(zip(p1, p2)):
        (x1, y1, *_), (x2, y2, *_) = m1[i1], m2[i2]
        cv.line(res, (int(x1), int(y1)), (w1+int(x2), int(y2)), (0,0,255) if k!=i else (0,255,255), 1, cv.LINE_AA)
    return res