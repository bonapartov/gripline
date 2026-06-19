import 'package:equatable/equatable.dart';

class DriverProfile extends Equatable {
  final int id;
  final String name;
  final String slug;
  final String? city;
  final Map<String, dynamic>? ratingByClass;

  const DriverProfile({
    required this.id,
    required this.name,
    required this.slug,
    this.city,
    this.ratingByClass,
  });

  factory DriverProfile.fromJson(Map<String, dynamic> json) {
    return DriverProfile(
      id: json['id'] as int,
      name: json['name'] as String,
      slug: json['slug'] as String,
      city: json['city'] as String?,
      ratingByClass: json['rating_by_class'] as Map<String, dynamic>?,
    );
  }

  // Лучший рейтинг среди всех классов (0–100)
  double? get bestRating {
    if (ratingByClass == null || ratingByClass!.isEmpty) return null;
    return ratingByClass!.values
        .map((v) => (v['score'] as num?)?.toDouble() ?? 0.0)
        .reduce((a, b) => a > b ? a : b);
  }

  @override
  List<Object?> get props => [id, name, slug];
}
