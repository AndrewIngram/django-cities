#!/usr/bin/env python
"""
GeoNames city data import script. Requires the following files:
- http://download.geonames.org/export/dump/countryInfo.txt
- http://download.geonames.org/export/dump/admin1Codes.txt
- http://download.geonames.org/export/dump/cities1000.zip
Based on Richard Crowley's Django Shell Script https://gist.github.com/79156

Part of django-cities by Ben Dowling
"""

import os
import sys
sys.path[0] = os.path.normpath(os.path.join(sys.path[0], '..', '.'))
from django.core.management import setup_environ
import settings
setup_environ(settings)
import datetime
from friends.models import Friendship
from friends.views import friendship_request
from django.contrib.gis.geos import Point
from django.template.defaultfilters import slugify
from cities.models import *
import codecs
from django.db.models import Count

def import_countries():
	for line in open("countryInfo.txt"):
		if line[0] == "#":
			continue

		items = line.split("\t")
		country = Country()
		country.code = items[0]
		country.name = items[4]
		country.population = items[7]
		country.continent = items[8]
		country.tld = items[9][1:] # strip the leading .

		# Some smaller countries share a TLD. Save the one with the biggest population
		existing = Country.objects.filter(tld=country.tld)
		if existing.count():
			existing = existing[0]
			if existing.population < country.population:
				existing.delete()
				country.save()
				print "Replaced country %s with %s" % (existing.name, country.name)
		else:
			country.save()
			print "Added country %s %s" % (country.name, country.code)

def import_regions():
	for line in codecs.open("admin1Codes.txt", "r", "utf-8"):
		if line[0] == "#":
			continue

		items = line.split("\t")
		region = Region()
		region.code = items[0]
		region.name = items[1].strip()
		region.slug = slugify(region.name)
		try:
			region.country = Country.objects.get(code=region.code[:2])
		except:
			print "Cannot find country %s - skipping" % region.code[:2]
			continue

		region.save()
		print "Added region %s" % (region.name,)

def import_cities():
	for line in codecs.open("cities1000.txt", "r", "utf-8"):
		if line[0] == "#":
			continue

		items = line.split("\t")
		admin_type = items[11]
		type = items[7]

		# See http://www.geonames.org/export/codes.html
		if type in ['PPL', 'PPLA', 'PPLC', 'PPLA2', 'PPLA3', 'PPLA4'] and (type == 'PPLC' or admin_type != 'GLA'):
			city = City()
			city.id = items[0]
			city.name = items[1]
			city.slug = slugify(city.name)
			city.location = Point(float(items[4]), float(items[5]))
			city.population = items[14]

			region = None
			if items[11].strip():
				try:
					code = "%s.%s" % (items[8], items[11]) # Try more specific region first
					region = Region.objects.get(code=code.strip())
				except:
					pass

			if not region:
				try:
					code = "%s.%s" % (items[8], items[10])
					region = Region.objects.get(code=code.strip())
				except:
					print "Cannot find region %s for %s - skipping" % (code, city.name)
					continue
			city.region = region
			try:
				city.save()
			except:
				continue
			#print "Added city %s" % city

def fix_regions():
	"""Some large cities are placed in their own region. Fix those"""
	regions = Region.objects.annotate(count=Count('city')).filter(count=1)
	for r in regions:
		city = r.city_set.all()[0]
		try:
			nearest_cities = City.objects.filter(region__country=r.country).annotate(count=Count('region__city')).filter(count__gt=1).distance(city.location).order_by('distance')[:4] # 0 would be the same city, 1 is the nearest
			nearest_regions = {}
			for c in nearest_cities:
				nearest_regions[c.region] = 1 + nearest_regions.get(c.region, 0)
			nearest_regions = sorted(nearest_regions.iteritems(), key=lambda (k,v): (v,k))
			nearest_regions.reverse()
			nearest_region = nearest_regions[0][0]
			#print "Would move %s from %s ==> %s" % (city.name, r, nearest_region)
			city.region = nearest_region
			city.save()
		except:
			pass
def import_districts():
	for line in codecs.open("cities1000.txt", "r", "utf-8"):
		if line[0] == "#":
			continue

		items = line.split("\t")

		admin_type = items[11]
		type = items[7]

		# See http://www.geonames.org/export/codes.html
		if type == 'PPLX' or (admin_type == 'GLA' and type != 'PPLC'):
			district = District()
			district.id = items[0]
			district.name = items[1]
			district.slug = slugify(district.name)
			district.location = Point(float(items[4]), float(items[5]))
			district.population = items[14]
			if admin_type == 'GLA':
				district.city = City.objects.filter(name='London').order_by('-population')[0] # Set city to London, UK
			else:
				district.city = City.objects.filter(population__gt=125000).distance(district.location).order_by('distance')[0] # Set the nearest city
			district.save()
			print "Added district %s" % district

def cleanup():
	""" Delete all countries and regions that don't have any children, and any districts that are single children"""

	# Fix places in "United Kingdom (general)
	r = Region.objects.get(name='United Kingdom (general)')
	for city in r.city_set.all():
		try:
			nearest_cities = City.objects.filter(region__country=r.country).distance(city.location).exclude(region=r).order_by('distance')[:5] # 0 would be the same city, 1 is the nearest
			nearest_regions = {}
			for c in nearest_cities:
				nearest_regions[c.region] = 1 + nearest_regions.get(c.region, 0)
			nearest_regions = sorted(nearest_regions.iteritems(), key=lambda (k,v): (v,k))
			nearest_regions.reverse()
			nearest_region = nearest_regions[0][0]
			print "Moving %s to %s ==> %s" % (city.name, r, nearest_region)
			city.region = nearest_region
			city.save()
		except:
			pass


	single_districts = District.objects.annotate(count=Count('city__district')).filter(count=1)
	single_districts.delete()

	empty_regions = Region.objects.filter(city__isnull=True)
	empty_regions.delete()

	empty_countries = Country.objects.filter(region__isnull=True)
	empty_countries.delete()

if '__main__' == __name__:
	import_countries()
	import_regions()
	import_cities()
	import_districts()
	fix_regions()
	cleanup()
