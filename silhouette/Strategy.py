# (c) 2013 jw@suse.de
#
# Strategy.py -- cut strategy algorithms for a Graphtec Silhouette Cameo plotter.
#
# In order to support operation without a cutting mat, a strategic
# rearrangement of cuts is helpful.
# e.g. 
#  * With a knive, sharp turns are to be avoided. They easily rupture the paper.
#  * With some pens, the paper may become unstable if soaked with too much ink.
#    Avoid backwards or inwards strokes.
#  * In general, cut paper is fragile. Do not move backwards and cut, where other cuts 
#    were placed. We require (strict) monotonic progression along the sheet with 
#    minimal backwards movement.
#
# 2013-05-21, jw, V0.1  -- initial draught.
# 2013-05-23, jw, V0.2  -- dedup, subdivide, two options for sharp turn detectors added.
#                          draft for simple_barrier() added.
# 2013-05-25, jw, V0.3  -- corner_detect.py now jumps when not cutting.
#                          Strategy.py: new code: mark_segment_done(), append_or_extend_simple().
#                          completed process_simple_barrier(), tested, debugged, verbose level reduced.
#                          The current slicing and sharp corner strategy appears useful.
# 2013-05-26, jw, V1.0  -- adopted version number from inkscape_silhouette package.
#                          improved path extension logic in append_or_extend_hard(), 
#                          much better, but still not perfect.
#                          Verbose printf's to stderr, so that inkscape survives.  
# 2013-05-26, jw, V1.1  -- path_overshoot() added, this improves quality 
#                          and the paper now comes apart by itself.
#                          Added algorithm prose for process_pyramids_barrier()
# 2013-05-31, jw, V1.3  -- renamed sharp_turn() to sharp_turn_90, added sharp_turn_45(), sharp_turn_63()
#                          Using .x, .y syntax provided by class XY_a() instead of [0], [1] everywhere.
#                          ccw() and sharp_turn*() now global. No class needed.
#                          Using class Barrier from Geomentry in the main loop of pyramids_barrier()

import copy
import math
import sys      # only for debug printing.

from silhouette.Geometry import *


presets = {
  'default': {
    'pyramids_algorithm': False,
    'corner_detect_min_jump': 2,
    'corner_detect_dup_epsilon': 0.1,
    'monotone_allow_back_travel': 10.0,
    'sharp_turn_fwd_ratio': 0.0,
    'barrier_increment': 10.0,
    'overshoot': 0.2,     # works well with 80g paper
    'tool_pen': False,
    'verbose': 1
    },
  'pyramids': {
    'pyramids_algorithm': True,
    'monotone_allow_back_travel': 10.0,
    'sharp_turn_fwd_ratio': 0.5,
    'overshoot': 0.2,     # works well with 80g paper
    'tool_pen': False,
    'do_slicing': True,
    'verbose': 1
    },
  'nop': {
    'do_dedup': False,
    'do_subdivide': False,
    'do_slicing': False,
    'overshoot': 0,
    'tool_pen': False,
    'verbose': 2
  }
}

class MatFree:
  def __init__(self, preset="default", scale=1.0, pen=None):
    """This initializer defines settings for the apply() method.
       A scale factor is applied to convert input data units to mm.
       This is needed, as the length units used in presets are mm.
    """
    self.verbose  = 0
    self.do_dedup = True
    self.do_subdivide = True
    self.do_slicing = True
    self.tool_pen = False
    self.barrier_increment = 3.0
    self.monotone_allow_back_travel = 3.0
    self.sharp_turn_fwd_ratio = 0.99     # 0.5 == 63 deg
    self.input_scale = scale
    self.pyramids_algorithm = False

    self.preset(preset)

    if pen is not None:
      self.tool_pen = pen

    self.points = []
    self.points_dict = {}
    self.paths = []

  def list_presets(self):
    return copy.deepcopy(presets)

  def preset(self, pre_name):
    if not pre_name in presets:
      raise ValueError(pre_name+': no such preset. Try "'+'", "'.join(presets.keys())+'"')
    pre = presets[pre_name]
    for k in pre.keys():
      self.__dict__[k] = pre[k]

  def export(self):
    """reverse of load(), except that the nodes are tuples of
       [x, y, { ... attrs } ]
       Most notable attributes:
       - 'sharp', it is present on nodes where the path turns by more 
          than 90 deg.
    """
    cut = []
    for path in self.paths:
      new_path = []
      for pt in path:
        new_path.append(self.points[pt])
      cut.append(new_path)
    return cut

  def pt2idx(self, x,y):
    """all points have an index, if the index differs, the point 
       is at a different locations. All points also have attributes
       stored with in the point object itself. Points that appear for the second
       time receive an attribute 'dup':1, which is incremented on further reoccurences.
    """

    k = str(x)+','+str(y)
    if k in self.points_dict:
      idx = self.points_dict[k]
      if self.verbose:
        print >>sys.stderr, "%d found as dup" % idx
      if 'dup' in self.points[idx].attr:
        self.points[idx].dup += 1
      else:
        self.points[idx].dup = 1
    else:
      idx = len(self.points)
      self.points.append(XY_a((x,y)))
      self.points_dict[k] = idx
      self.points[idx].id = idx
    return idx

  def load(self, cut):
    """load a sequence of paths. 
       Nodes are expected as tuples (x, y).
       We extract points into a seperate list, with attributes as a third 
       element to the tuple. Typical attributes to be added by other methods
       are refcount (if commented in), sharp (by method mark_sharp_segs(), 
       ...
    """

    for path in cut:
      new_path = []
      for point in path:
        idx = self.pt2idx(self.input_scale * point[0], self.input_scale * point[1])

        if len(new_path) == 0 or new_path[-1] != idx or self.do_dedup == False:
          # weed out repeated points
          new_path.append(idx)
          # self.points[idx].refcount += 1
      self.paths.append(new_path)


  def link_points(s):
    """add segments (back and forth) between connected points.
    """
    for path in s.paths:
      A = None
      for pt in path:
        if A is not None:
          if 'seg' in s.points[A].attr:
            s.points[A].seg.append(pt)
          else:
            s.points[A].seg = [ pt ]

          if 'seg' in s.points[pt].attr:
            s.points[pt].seg.append(A)
          else:
            s.points[pt].seg = [ A ]
        A = pt


  def subdivide_segments(s, maxlen):
    """Insert addtional points along the paths, so that
       no segment is longer than maxlen
    """
    if s.do_subdivide == False:
      return
    maxlen_sq = maxlen * maxlen
    for path_idx in range(len(s.paths)):
      path = s.paths[path_idx]
      new_path = []
      for pt in path:
        if len(new_path):
          A = new_path[-1]
          dist_a_pt_sq = dist_sq(s.points[A], s.points[pt])
          if dist_a_pt_sq > maxlen_sq:
            dist = math.sqrt(dist_a_pt_sq)
            nsub = int(dist/maxlen)
            seg_len = dist/float(nsub+1)
            dx = (s.points[pt].x - s.points[A].x)/float(nsub+1)
            dy = (s.points[pt].y - s.points[A].y)/float(nsub+1)
            if s.verbose > 1:
              print >>sys.stderr, "pt%d -- pt%d: need nsub=%d, seg_len=%g" % (A,pt,nsub,seg_len)
              print >>sys.stderr, "dxdy", dx, dy, "to", (s.points[pt].x, s.points[pt].y), "from", (s.points[A].x,s.points[A].y)
            for subdiv in range(nsub):
              sub_pt =s.pt2idx(s.points[A].x+dx+subdiv*dx, 
                               s.points[A].y+dy+subdiv*dy)
              new_path.append(sub_pt)
              s.points[sub_pt].sub = True
              if s.verbose > 1:
                print >>sys.stderr, "   sub", (s.points[sub_pt].x, s.points[sub_pt].y)
        new_path.append(pt)
      s.paths[path_idx] = new_path




  def mark_sharp_segs(s):
    """walk all the points and check their segments attributes, 
       to see if there are connections that form a sharp angle.
       This needs link_points() to be called earlier.
       One sharp turn per point is enough to make us careful.
       We don't track which pair of turns actually is a sharp turn, if there
       are more than two segs. Those cases are rare enough to allow the inefficiency.

       TODO: can honor corner_detect_min_jump? Even if so, what should we do in the case
       where multiple points are so close together that the paper is likely to tear?
    """
    for pt in s.points:
      if 'sharp' in pt.attr:
        ## shortcut existing flags. One sharp turn per point is enough to make us careful.
        ## we don't want to track which pair of turns actually is a sharp turn, if there
        ## are more than two segments per point. Those cases are rare enough 
        ## to handle them inefficiently.
        continue
      if 'seg' in pt.attr:
        ll = len(pt.seg)
        # if ll > 4:
        #   ## You cannot attach 5 lines to a point without creating one sharp angle.
        #   ## This is true for sharp turn defined as >90 degree.
        #   pt.sharp = True
        #   continue
        ## look at each pair of segments once, check their angle.
        for l1 in range(ll):
          A = s.points[pt.seg[l1]]
          for l2 in range(l1+1, ll):
            B = s.points[pt.seg[l2]]
            if sharp_turn(A,pt,B, s.sharp_turn_fwd_ratio):
              pt.sharp = True
          if 'sharp' in pt.attr:
            break
      else:
        print >>sys.stderr, "warning: no segments in point %d. Run link_points() before mark_sharp_segs()" % (pt.id)



  def mark_sharp_paths(s):
    """walk through all paths, and add an attribute { 'sharp': True } to the
       points that respond true with the sharp_turn() method.

       Caution: mark_sharp_paths() walks in the original order, which may be irrelevant 
       after reordering.

       This marks sharp turns only if paths are not intersecting or touching back. 
       Assuming segment counts <= 2. Use mark_sharp_segs() for the general case.
       Downside: mark_sharp_segs() does not honor corner_detect_min_jump.
    """
    min_jump_sq = s.corner_detect_min_jump * s.corner_detect_min_jump
    dup_eps_sq  = s.corner_detect_dup_epsilon * s.corner_detect_dup_epsilon

    idx = 1
    A = None
    B = None 
    for path in s.paths:
      if B is not None and len(path) and dist_sq(B, s.points[path[0]]) > min_jump_sq:
        # disconnect the path, if we jump more than 2mm
        A = None
        B = None
        
      for iC in path:
        C = s.points[iC]
        if B is not None and dist_sq(B,C) < dup_eps_sq:
          # less than 0.1 mm distance: ignore the point as a duplicate.
          continue

        if A is not None and sharp_turn(A,B,C, s.sharp_turn_fwd_ratio):
          B.sharp = True

        A = B
        B = C
      #
    #


  def append_or_extend_hard(s, seg):
    """adds a segment to the output list. The segment extends the previous segment, 
       if the last point if the previous segment is identical with our first 
       point.  If the segment has no sharp points, we double check if extend 
       would work with the inverted segment. Optionally also flipping around 
       the previous segment if it would help. (FIXME: this possibility should 
       be detected earlier)
       Otherwise, the segment is appended as a new path.
    """
    if not 'output' in s.__dict__: s.output = []
    if len(s.output) and s.verbose > 1:
      print >>sys.stderr, "append_or_extend_hard...", s.output[-1][-1], seg
    if (len(s.output) > 0 and len(s.output[-1]) >= 2 and 
         'sharp' not in s.output[-1][0] and
         'sharp' not in s.output[-1][-1]):
      # we could flip around the previous segment, if needed:
      if (s.output[-1][0].id == seg[0].id or
          s.output[-1][0].id == seg[-1].id):
        # yes, flipping the previous segment, will help below. do it.
        s.output[-1] = list(reversed(s.output[-1]))
        if s.verbose:
          print >>sys.stderr, "late flip ", len(s.output), len(s.output[-1])
      #
    #

    if len(s.output) > 0 and s.output[-1][-1].id == seg[0].id:
      s.output[-1].extend(seg[1:])
      if s.verbose > 1:
        print >>sys.stderr, "... extend"
    elif len(s.output) > 0 and s.output[-1][-1].id == seg[-1].id:
      ## check if we can turn it around
      if 'sharp' not in s.output[-1][-1].attr and 'sharp' not in seg[-1].attr and 'sharp' not in seg[0].attr:
        s.output[-1].extend(list(reversed(seg))[1:])
        if s.verbose > 1:
          print >>sys.stderr, "... extend reveresed"
      else:
        s.output.append(seg)
        if s.verbose > 1:
          print >>sys.stderr, "... append"
      #
    else:
      s.output.append(seg)
      if s.verbose > 1:
        print >>sys.stderr, "... append"
    #


  def append_or_extend_simple(s, seg):
    """adds a segment to the output list. The segment extends the previous segment, 
       if the last point if the previous segment is identical with our first 
       point.  
       Otherwise, the segment is appended as a new path.
    """
    if not 'output' in s.__dict__: s.output = []
    if len(s.output) and s.verbose > 1:
      print >>sys.stderr, "append_or_extend_simple...", s.output[-1][-1], seg

    if len(s.output) > 0 and s.output[-1][-1].id == seg[0].id:
      s.output[-1].extend(seg[1:])
      if s.verbose > 1:
        print >>sys.stderr, "... extend"
    else:
      s.output.append(seg)
      if s.verbose > 1:
        print >>sys.stderr, "... append"
    #


  def mark_segment_done(s, A,B):
    """process_simple_barrier ignores points and segments that have already been done.
       We call process_simple_barrier() repeatedly, but we want each segment only once.
       Also, a point with a sharp turn can be the start of a segment only once. 
       All its other segments need to be drawn towards such a point.
       mark_segment_done() places the needed markers for this logic.
    """
    A.seen = True
    B.seen = True
    iA = A.id
    iB = B.id
    a_seg_todo = False
    b_seg_todo = False
    for iS in range(len(A.seg)):
      if A.seg[iS] == iB: A.seg[iS] = -iB or -1000000000
      if A.seg[iS] >= 0: a_seg_todo = True
    for iS in range(len(B.seg)):
      if B.seg[iS] == iA: B.seg[iS] = -iA or -1000000000
      if B.seg[iS] >= 0: b_seg_todo = True

    # CAUTION: is this really helpful?:
    ## it prevents points from a slice to go into process_simple_barrier()'s segment list,
    ## but it also hides information....
    if not a_seg_todo: s.points[iA] = None
    if not b_seg_todo: s.points[iB] = None

  def process_pyramids_barrier(s, y_slice, max_y, left2right=True):
    """ finding the next point involves overshadowing other points.
        Our assumption is, that it is save to cut the paper at point A, 
        whenever there is a triangle sitting on the baseline (where the 
        transport rollers are) with 2x 45 degree coming from both sides, 
        meeting at 90 degrees at point A, so that the inside of the 
        triangle is free of any cuts.

        We prefer to cut away from the rollers, if possible, but that is 
        subordinate rule -- applicable, whenever the cut direction can 
        be freely chosen. If point A is already part of a cut, then we cut the
        path A-B always towards A, never starting at A.

        A horizontal barrier Y_bar exists, that limits our downwards movement temporarily.
        We assume to be called again with lowered Y_bar (increased max_y, it counts downwards).

        Another barrier Xf_bar is a forward slanted 45 degree barrier that is swept sideways. 
        Points become eligible, if they are above Y_bar and behind Xf_bar.

        We start with the sideways barrier from left to right aka increasing x.
        In this case 'behind' means to the left of Xf_bar. (Every second sweep
        will be the opposite direction, but below only left to right is
        discussed).
        The very first point that is behind Xf_bar is the starting point A. Then we iterate:

        From any previous point A, we prefer to follow a line segment to reach 
        the next point B.  Segments are eligible, if their B is rightward from A, 
        (B.x greater or equal A.x). We chose the segment with the lowest B.y coordinate
        if there is any choice and check the following conditions:

        a) B is below Y_bar. 
           Compute point C as the intersection of Y_bar with A-B. Replace 
           the segment A-B by segments A-C, C-B. Let B and C swap names.
        b) B is 45 degrees or more downwards from A (B.x-A.x < B.y-A.y) 
           We make an extra check to see if B would overshadow any point in the other 
           direction. Temporarily apply a backwards slanted barrier Xb_bar in A. 
           While moving the barrier to B, stop at the first point D that it hits, if any.
           If so, position Xb_bar in D, compute point E as the intersection of Xb_bar 
           with A-B. Replace the segment A-B by segments A-E, E-B. 
           If we have a point C remembered from a), then replace segments E-B, B-C with E-C 
           and garbage collect point B. 
           Let B and E swap names.

        If we now have no B, then we simply move the sideways barrier to reveal our 
        next A -- very likely a jump rather than a cut. If no todo segments are left in 
        the old A, drop that old A. Iterate.

        But if we have a B, then we tentatively advance Xf_bar from A to B and 
        record all new points F[] in the order we pass them. We don't care about them, if 
        they are all 'below' (on the right hand side of) segment A-B.
        For the first point F, that has ccw(A,B,F) == True, we position Xf_bar in F, if any.
        If so, we compute point G as the intersection of Xf_bar with A-B. Replace the segment 
        A-B by segments A-G, G-B. We cut segment A-G. We make F our next A - very likely a jump.
        If no todo segments are left in the old A, drop that old A. Iterate.

        If iteration exhausts, we are done with this processing sweep and
        report back the lowest remaining min_y coordinate of all points we left
        behind with segments todo. The next sweep will go the other direction.

        Caller should call us again with direction toggled the other way, and
        possibly advancing max_y = min_y + monotone_allow_back_travel. The
        variable barrier_increment is not used here, as we compute the
        increment.

        In the above context, 'cutting' a segment means, to add it to the output
        list to deactivate its seg[] entries in the endpoints. Endpoints
        without active segments do not contribute to the min_y computation
        above, they are dropped.

        When all points are dropped, we did our final sweep and return min_y =
        None.  It is caller's responsibility to check the direction of each cut
        in the s.output list with regards to sharp points and cutting-towards-the-rollers.

        Assert that we cut at least one segment per sweep or drop at least one
        point per sweep.  Also the number of added segments and points should
        be less than what we eventually output and drop.  
        If not, the above algorithm may never end.

    """
    Xf_bar = Barrier(y_slice, key=lambda a: a[0]-a[1])
    y_slice[0].speed = 21
    if 'speed' in y_slice[0].attr:
      print "yes"
    print y_slice, max_y, y_slice[0].attr, y_slice[0].seg
    if max_y > 20: return None
    return max_y - 1


  def process_simple_barrier(s, y_slice, max_y, last_x=0.0):
    """process all lines that segment points in y_slice.
       the slice is examined using a scan-strategy. Either left to right or
       right to left. last_x is used to deceide if the the left or 
       right end of the slice is nearest. We start at the nearer end, and
       work our way to the farther end.
       All line segments that are below max_y are promoted into the output list, 
       with a carefully chosen ordering and direction. append_or_extend_hard()
       is used to merge segments into longer paths where possible.

       The final x-coordinate is returned, so that the caller can provide us
       with its value on the next call.
    """
    if s.verbose:
      print >>sys.stderr, "process_simple_barrier limit=%g, points=%d, %s" % (max_y, len(y_slice), last_x)
      print >>sys.stderr, "                max_y=%g" % (y_slice[-1].y)

    min_x = None
    max_x = None

    segments = []
    for pt in y_slice:
      if pt is None:            # all segments to that point are done.
        continue
      for iC in pt.seg:
        if iC < 0:              # this segment is done.
          continue
        C = s.points[iC]
        if C is not None and C.y <= max_y:
          if s.verbose > 1:
            print >>sys.stderr, "   segments.append", C, pt
          segments.append((C,pt))
          if min_x is None or min_x >  C.x: min_x =  C.x
          if min_x is None or min_x > pt.x: min_x = pt.x
          if max_x is None or max_x <  C.x: max_x =  C.x
          if max_x is None or max_x < pt.x: max_x = pt.x
          s.mark_segment_done(C,pt)
        #
      #
    #
    
    left2right = s.decide_left2right(min_x, max_x, last_x)
    xsign = -1.0
    if left2right: xsign = 1.0
    def dovetail_both_key(a):
      return a[0].y+a[1].y+xsign*(a[0].x+a[1].x)
    segments.sort(key=dovetail_both_key)

    for segment in segments:
      ## Flip the orientation of each line segment according to this strategy:
      ## check 'sharp' both ends. (sharp is irrelevent without 'seen')
      ##   if one has 'sharp' (and 'seen'), the other not, then cut towards the 'sharp' end.
      ##   if none has that, cut according to decide_left2right()
      ##   if both have it, we must subdivide the line segment, and cut from the 
      ##   midpoint to each end, in the order indicated by decide_left2right().
      A = segment[0]
      B = segment[1]
      if 'sharp' in A.attr and 'seen' in A.attr:
        if 'sharp' in B.attr and 'seen' in B.attr:              # both sharp
          iM = s.pt2idx((A.x+B.x)*.5, (A.y+B.y)*.5 )
          M = s.points[iM]
          if xsign*A.x <= xsign*B.x:
            s.append_or_extend_hard([M, A])
            s.append_or_extend_hard([M, B])
          else:
            s.append_or_extend_hard([M, B])
            s.append_or_extend_hard([M, A])
        else:                                                   # only A sharp
          s.append_or_extend_hard([B, A])
      else:
        if 'sharp' in B.attr and 'seen' in B.attr:              # only B sharp
          s.append_or_extend_hard([A, B])
        else:                                                   # none sharp
          if xsign*A.x <= xsign*B.x:
            s.append_or_extend_hard([A, B])
          else:
            s.append_or_extend_hard([B, A])
          #
        #
      #
          
    # return the last x coordinate of the last stroke
    if not 'output' in s.__dict__: return 0
    return s.output[-1][-1].x


  def decide_left2right(s, min_x, max_x, last_x=0.0):
    """given the current x coordinate of the cutting head and
       the min and max coordinates we need to go through, compute the best scan direction, 
       so that we minimize idle movements.
       Returns True, if we should jump to the left end (aka min_x), then work our way to the right.
       Returns False, if we should jump to the right end (aka max_x), then work our way to the left.
       Caller ensures that max_x is >= min_x. ("The right end is to the right of the left end")
    """
    if min_x >= last_x: return True     # easy: all is to the right
    if max_x <= last_x: return False    # easy: all is to the left.
    if abs(last_x - min_x) < abs(max_x - last_x):
      return True                       # the left edge (aka min_x) is nearer
    else:
      return False                      # the right edge (aka max_x) is nearer

  def pyramids_barrier(s):
    """Move a barrier in ascending y direction.
       For each barrier position, find connected segments that are as high above the barrier 
       as possible. A pyramidonal shadow (opening 45 deg in each direction) is cast upward
       to see if a point is acceptable for the next line segment. If the shadow touches other points,
       that still have line segment not yet done, we must chose one of these points first.

       While obeying this shadow rule, we also sweep left and right through the data, similar to the
       simple_barrier() algorithm below.
    """
    s.output = []
    if not s.do_slicing:
      for path in s.paths:
        s.output.append([])
        for idx in path:
          s.output[-1].append(s.points[idx])
          if idx == 33: print s.points[idx].attr
        #
      #
      return

    Y_bar = Barrier(s.points, key=lambda a: a[1])

    min_y = 0
    barrier_y = min_y + s.monotone_allow_back_travel
    dir_toggle = True
    len_output = len(s.output)
    while True:
      Y_bar.find((0, barrier_y))
      min_y = s.process_pyramids_barrier(Y_bar.pslice(), barrier_y, left2right=dir_toggle)
      if len(s.output) == len_output:
        raise ValueError("output list unchanged after process_pyramids_barrier(): "+str(len_output))
      len_output = len(s.output)
      if min_y is None:
        break
      dir_toggle = not dir_toggle
      barrier_y = min_y + s.monotone_allow_back_travel
    #


  def simple_barrier(s):
    """move a barrier in ascending y direction. 
       For each barrier position, only try to cut lines that are above the barrier.
       Flip the sign for all segment ends that were cut to negative. This flags them as done.
       Add a 'seen' attribute to all nodes that have been visited once.
       When no more cuts are possible, then move the barrier, try again.
       A point that has all segments with negative signs is removed.

       Input is read from s.paths[] -- having lists of point indices.
       The output is placed into s.output[] as lists of XY_a() objects
       by calling process_simple_barrier() and friends.
    """

    if not s.do_slicing:
      s.output = []
      for path in s.paths:
        s.output.append([])
        for idx in path:
          s.output[-1].append(s.points[idx])
        #
      #
      return
          
    ## first step sort the points into an additional list by ascending y.
    def by_y_key(a):
      return a.y
    sy = sorted(s.points, key=by_y_key)

    barrier_y = s.barrier_increment
    barrier_idx = 0     # pointing to the first element that is beyond.
    last_x = 0.0        # we start at home.
    while True:
      old_idx = barrier_idx
      while sy[barrier_idx].y < barrier_y:
        barrier_idx += 1
        if barrier_idx >= len(sy):
          break
      if barrier_idx > old_idx:
        last_x = s.process_simple_barrier(sy[0:barrier_idx], barrier_y, last_x=last_x)       
      if barrier_idx >= len(sy):
        break
      barrier_y += s.barrier_increment
    #
 

  def apply_overshoot(s, paths, start_travel, end_travel):
    """Extrapolate path in the output list by the give travel at start and/or end
       Paths are extended linear, curves are not taken into accound.
       The intended effect is that interrupted cuts actually overlap at the 
       split point. The knive may otherwise leave some uncut material around 
       the split point.
    """
    def extend_b(A,B,travel):
      d = math.sqrt(dist_sq(A,B))
      if d < 0.000001: return B         # cannot extrapolate if A == B
      ratio = travel/d
      dx = B.x-A.x
      dy = B.y-A.y
      C = XY_a((B.x+dx*ratio,  B.y+dy*ratio))
      if 'sharp' in B.attr: C.sharp = True
      return C

    for path in paths:
      if start_travel > 0.0:
        path[0] = extend_b(path[1],path[0], start_travel)
      if end_travel > 0.0:
        path[-1] = extend_b(path[-2],path[-1], end_travel)

    return paths


  def apply(self, cut):
    self.load(cut)
    if self.pyramids_algorithm:
      self.link_points()
      self.mark_sharp_segs()
      self.pyramids_barrier() 
    else:
      self.subdivide_segments(self.monotone_allow_back_travel)
      self.link_points()
      self.mark_sharp_segs()
      self.simple_barrier()
    if self.tool_pen == False and self.overshoot > 0.0:
      self.output = self.apply_overshoot(self.output, self.overshoot, self.overshoot)

    return self.output

